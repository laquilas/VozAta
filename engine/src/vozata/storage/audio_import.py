"""`AudioFileImporter`: an audio file recorded elsewhere as a new meeting (phase 60).

The file goes into the **system** track, the one speaker identification runs on; the mic track
is silence of the same length (`repair`). `session.json` is written last, as a capture that just
ended (`finalizing` with `capture_ended_at`): until then the session is not listed, and from then
on the processing queue, or a restarted engine (`SessionManager.resume_pending`), takes it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Protocol, runtime_checkable

from vozata.config import Settings
from vozata.domain import Channel
from vozata.ports import (
    AudioDecodeError,
    AudioDecoder,
    AudioMixer,
    PcmImport,
    RecoverableStore,
    SessionAudio,
    SessionRepository,
)
from vozata.session_meta import SessionMeta
from vozata.session_title import MAX_TITLE_LENGTH, normalize_title

_log = logging.getLogger(__name__)


@runtime_checkable
class ImportableAudio(SessionAudio, PcmImport, RecoverableStore, Protocol):
    """Both audio stores: a channel written at once, then the other padded to its length."""


@dataclass(frozen=True)
class _Components:
    """What `SessionMeta` reads of a recording, for a meeting that had no devices."""

    minutes_template: str
    vocabulary: tuple[str, ...]
    title: str | None
    device_names: dict[Channel, str]
    live_transcription: bool = False


class AudioFileImporter:
    """Reads the file with an `AudioDecoder` into the configured storage backend."""

    def __init__(
        self,
        repository: SessionRepository,
        audio: ImportableAudio,
        decoder: AudioDecoder,
        settings: Callable[[], Settings],
        mixer: AudioMixer,
        *,
        vocabulary: Callable[[], Sequence[str]] = tuple,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repository
        self._audio = audio
        self._decoder = decoder
        self._settings = settings
        self._mixer = mixer
        self._vocabulary = vocabulary
        self._now = now or repository.now

    def import_file(self, path: Path, name: str, recorded_at: datetime | None) -> str:
        """A new meeting from the file at `path` (`name` is the user's file name); it ends at
        `recorded_at` (the file's time) or now. Returns its id; raises `AudioDecodeError`
        (`audio_empty` for a file without samples), and then no meeting is left."""
        settings = self._settings()
        imported_at = self._now()
        end = recorded_at or imported_at
        estimate = self._decoder.duration(path) or 0.0
        session_id = self._repo.create(end - timedelta(seconds=estimate))
        try:
            frames = self._audio.import_pcm(session_id, Channel.SYSTEM, self._decoder.blocks(path))
            if frames == 0:
                raise AudioDecodeError("audio_empty")
            self._audio.repair(session_id)  # the silent mic track
            self._audio.write_mix(session_id, self._mixer)
            duration = frames / settings.sample_rate
            meta = SessionMeta(
                self._repo,
                session_id,
                end - timedelta(seconds=round(duration)),
                settings,
                _Components(
                    settings.minutes_template,
                    tuple(self._vocabulary()),
                    _title(name),
                    {},
                ),
            )
            meta.imported(imported_at, duration, name)
            meta.set_language(settings.transcription_language, "selected")
        except BaseException:
            self._drop(session_id)
            raise
        return session_id

    def _drop(self, session_id: str) -> None:
        try:
            self._repo.discard(session_id)  # the folder, or the row and its chunks (cascade)
        except Exception:
            _log.exception("Could not remove the half-imported session %s", session_id)


def _title(name: str) -> str | None:
    """The file name without its extension (and without any folder a client sent)."""
    stem = PurePath(name.replace("\\", "/")).stem
    return normalize_title(stem[:MAX_TITLE_LENGTH])
