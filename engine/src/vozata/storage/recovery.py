"""Crash recovery (phase 17): find interrupted sessions and repair their files.

A session whose metadata still says `recording`, `paused` or `finalizing` while nothing is
recording it was cut short by a crash. Each `RecoverableStore` repairs its part (file backend:
WAV headers and equal track lengths, then a half-written last transcript line set aside); the
meeting is then finished by its processing job (phase 40: the repair step, the transcription of
what is missing and the stop steps, `bootstrap_processing.build_processing_job`). Recovery never
deletes data: if the data cannot be repaired the session stays `interrupted` with the reason in
its metadata (`recovery_error`).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from vozata.domain import SessionStatus
from vozata.ports import RecoverableStore, SessionRepository

_ACTIVE = {
    SessionStatus.RECORDING.value,
    SessionStatus.PAUSED.value,
    SessionStatus.FINALIZING.value,
}

_log = logging.getLogger(__name__)


def find_interrupted(
    store: SessionRepository,
    live_ids: Collection[str] = (),
    *,
    stale_after: float = 0.0,
) -> list[str]:
    """Ids of the `interrupted` sessions, newest first, except those in `live_ids`.

    `live_ids` are the sessions this process is running (recording or being recovered). Any other
    session still `recording` / `paused` / `finalizing` is marked `interrupted` first. With
    `stale_after` > 0 it must also have had no heartbeat (else no start) for that many seconds, so
    a session another process is recording right now is left alone. A session with
    `capture_ended_at` is never marked: capture ended cleanly and its processing job is queued (or,
    for the CLI `record`, running inline in another process, whose heartbeat has stopped); the
    server re-queues it at start (`SessionManager.resume_pending`).
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
            if meta.get("capture_ended_at"):
                continue
            if stale_after > 0 and not _stale(meta, store.now(), stale_after):
                continue
            store.write_meta(session_id, {**meta, "status": SessionStatus.INTERRUPTED.value})
            _log.warning("Session %s was interrupted while %s", session_id, status)
            status = SessionStatus.INTERRUPTED.value
        if status == SessionStatus.INTERRUPTED.value:
            found.append(session_id)
    return found


class SessionRecovery:
    """Find `interrupted` sessions and repair their files; the processing job finishes them."""

    def __init__(
        self,
        store: SessionRepository,
        repairs: Sequence[RecoverableStore],
        stale_after: float = 0.0,
    ) -> None:
        """`repairs` run in order on `repair` (file backend: the audio, then the transcript)."""
        self._store = store
        self._repairs = tuple(repairs)
        self._stale_after = stale_after

    @property
    def store(self) -> SessionRepository:
        return self._store

    def find_interrupted(self, live_ids: Collection[str] = ()) -> list[str]:
        return find_interrupted(self._store, live_ids, stale_after=self._stale_after)

    def is_interrupted(self, session_id: str) -> bool:
        """Raises `SessionNotFoundError` for an unknown session."""
        status = self._store.read_meta(session_id).get("status")
        return status == SessionStatus.INTERRUPTED.value

    def is_resumable(self, session_id: str) -> bool:
        """A `finalizing` session with `capture_ended_at`: capture ended and only its processing
        job is missing (the CLI `record` crashed in its inline job)."""
        meta = self._store.read_meta(session_id)
        return meta.get("status") == SessionStatus.FINALIZING.value and bool(
            meta.get("capture_ended_at")
        )

    def repair(self, session_id: str) -> float:
        """Repair the session's files (not its stop steps) and return its recorded length.

        Runs every repair in order and stops at the first failure (`StoreRepairError`); the
        recorded length is the longest one reported."""
        lengths = [repair.repair(session_id) for repair in self._repairs]  # stops at a failure
        return max((length for length in lengths if length is not None), default=0.0)

    def fail(self, session_id: str, reason: str) -> None:
        """Keep the session `interrupted` with `reason` as `recovery_error` (repair failed)."""
        meta = self._store.read_meta(session_id)
        meta["status"] = SessionStatus.INTERRUPTED.value
        meta["recovery_error"] = reason
        self._store.write_meta(session_id, meta)


def _stale(meta: dict[str, Any], now: datetime, stale_after: float) -> bool:
    stamp = meta.get("last_heartbeat_at") or meta.get("started_at")
    try:
        last = datetime.fromisoformat(stamp)
        return (now - last).total_seconds() > stale_after
    except (TypeError, ValueError):
        return True
