"""Crash recovery (phase 17): find interrupted sessions, repair their files, finish them.

A session whose `session.json` still says `recording`, `paused` or `finalizing` while nothing is
recording it was cut short by a crash. Its WAV headers are repaired, both tracks padded to the
same length, a half-written last transcript line set aside, and the session's own stop steps
(mix, speakers, minutes, search index, see `RecordingSession.recover`) run on it. Recovery never
deletes data: if the files cannot be repaired the session stays `interrupted` with the reason in
`session.json` (`recovery_error`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from vozata.domain import Channel, SessionStatus, TranscriptSegment
from vozata.ports import SessionObserver
from vozata.storage.session_store import SessionPaths, SessionStore
from vozata.storage.wav_repair import WavRepairError, pad_wav, repair_wav

_ACTIVE = {
    SessionStatus.RECORDING.value,
    SessionStatus.PAUSED.value,
    SessionStatus.FINALIZING.value,
}

_log = logging.getLogger(__name__)


class RecoveryError(RuntimeError):
    """The session's files could not be repaired; it stays `interrupted`."""


class RecoverableSession(Protocol):
    def recover(self, session_id: str, duration_seconds: float) -> None: ...


SessionBuilder = Callable[[str, SessionObserver], RecoverableSession]


def find_interrupted(
    store: SessionStore,
    live_ids: Collection[str] = (),
    *,
    stale_after: float = 0.0,
) -> list[str]:
    """Ids of the `interrupted` sessions, newest first, except those in `live_ids`.

    `live_ids` are the sessions this process is running (recording or being recovered). Any other
    session still `recording` / `paused` / `finalizing` is marked `interrupted` first. With
    `stale_after` > 0 it must also have had no heartbeat (else no start) for that many seconds, so
    a session another process is recording right now is left alone.
    """
    found: list[str] = []
    for session_id in store.list_sessions():
        try:
            meta = store.read_meta(session_id)
        except (OSError, ValueError):
            _log.warning("Skipping %s: unreadable session.json", session_id)
            continue
        status = meta.get("status")
        if session_id in live_ids:
            continue
        if status in _ACTIVE:
            if stale_after > 0 and not _stale(meta, store.now(), stale_after):
                continue
            store.write_meta(session_id, {**meta, "status": SessionStatus.INTERRUPTED.value})
            _log.warning("Session %s was interrupted while %s", session_id, status)
            status = SessionStatus.INTERRUPTED.value
        if status == SessionStatus.INTERRUPTED.value:
            found.append(session_id)
    return found


def repair_session_files(paths: SessionPaths, sample_rate: int) -> float:
    """Repair both WAVs, pad them to the longest one and set aside a damaged transcript tail.

    Returns the recorded length in seconds. Raises `WavRepairError` or `OSError`.
    """
    wavs = [paths.wav(channel) for channel in Channel]
    frames = max(repair_wav(wav, sample_rate) for wav in wavs)
    for wav in wavs:
        pad_wav(wav, frames)
    repair_transcript(paths.transcript_jsonl)
    return round(frames / sample_rate, 3)


def repair_transcript(path: Path) -> int:
    """Keep the readable lines of `transcript.jsonl`; move the others to `<name>.damaged`.

    A crash can cut the last line in half. Returns how many lines were moved (0: untouched).
    """
    if not path.is_file():
        return 0
    text = path.read_bytes().decode("utf-8", errors="replace")
    good: list[str] = []
    damaged: list[str] = []
    for line in text.splitlines():
        if line.strip():
            (good if _readable(line) else damaged).append(line)
    if not damaged:
        return 0
    side = path.with_name(path.name + ".damaged")
    with side.open("a", encoding="utf-8", newline="\n") as file:
        file.write("".join(line + "\n" for line in damaged))
    path.write_text("".join(line + "\n" for line in good), encoding="utf-8", newline="\n")
    _log.warning("Moved %d damaged line(s) of %s to %s", len(damaged), path, side.name)
    return len(damaged)


class SessionRecovery:
    """`recover(session_id, observer)`: repair an `interrupted` session and finish it."""

    def __init__(
        self,
        store: SessionStore,
        sample_rate: int,
        build_session: SessionBuilder,
        stale_after: float = 0.0,
    ) -> None:
        self._store = store
        self._rate = sample_rate
        self._build_session = build_session
        self._stale_after = stale_after

    @property
    def store(self) -> SessionStore:
        return self._store

    def find_interrupted(self, live_ids: Collection[str] = ()) -> list[str]:
        return find_interrupted(self._store, live_ids, stale_after=self._stale_after)

    def is_interrupted(self, session_id: str) -> bool:
        """Raises `SessionNotFoundError` for an unknown session."""
        status = self._store.read_meta(session_id).get("status")
        return status == SessionStatus.INTERRUPTED.value

    def recover(self, session_id: str, observer: SessionObserver) -> bool:
        """Finish an `interrupted` session; False (nothing done) for any other status.

        Raises `RecoveryError` when the files cannot be repaired (the reason is saved in
        `session.json` as `recovery_error`) and `SessionNotFoundError` for an unknown session.
        """
        if not self.is_interrupted(session_id):
            return False
        paths = self._store.paths(session_id)
        try:
            duration = repair_session_files(paths, self._rate)
        except (WavRepairError, OSError) as error:
            _log.warning("Recovering %s failed: %s", session_id, error)
            self._set_error(session_id, str(error))
            raise RecoveryError(str(error)) from error
        self._set_error(session_id, None)
        self._build_session(session_id, observer).recover(session_id, duration)
        return True

    def _set_error(self, session_id: str, reason: str | None) -> None:
        """Save (or clear, with None) `recovery_error` in `session.json`."""
        meta = self._store.read_meta(session_id)
        if reason is None and "recovery_error" not in meta:
            return
        meta.pop("recovery_error", None)
        if reason is not None:
            meta["recovery_error"] = reason
        self._store.write_meta(session_id, meta)


def _readable(line: str) -> bool:
    try:
        TranscriptSegment.from_dict(json.loads(line))
    except (ValueError, KeyError, TypeError):
        return False
    return True


def _stale(meta: dict[str, Any], now: datetime, stale_after: float) -> bool:
    stamp = meta.get("last_heartbeat_at") or meta.get("started_at")
    try:
        last = datetime.fromisoformat(stamp)
        return (now - last).total_seconds() > stale_after
    except (TypeError, ValueError):
        return True
