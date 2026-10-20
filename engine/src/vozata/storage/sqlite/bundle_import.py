"""`SqliteBundleImporter`: a meeting ZIP into `vozata.db` through the phase 33 importer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.domain import AudioTrack, Channel, ImportedSession
from vozata.ports import SessionNotFoundError
from vozata.storage.bundle_import import BundleError, SessionExistsError
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.migration import FolderImporter
from vozata.storage.session_store import SessionStore
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.repository import SqliteSessionRepository


class SqliteBundleImporter:
    """`BundleImporter`: a new session in one transaction, or the audio of a kept session that
    has none (its row is kept, as for a phase 31 folder)."""

    def __init__(
        self,
        repository: SqliteSessionRepository,
        audio: SqliteAudioStore,
        sample_rate: int,
        free_space: Callable[[Path], int] | None = None,
    ) -> None:
        self._repo = repository
        self._audio = audio
        self._rate = sample_rate
        self._free_space = free_space

    def import_folder(self, folder: Path) -> ImportedSession:
        """Also raises `NotEnoughSpaceError` when the disk is short of space."""
        session_id = folder.name
        restore = self._exists(session_id)
        if restore:
            has_wavs = any((folder / f"{channel.value}.wav").is_file() for channel in Channel)
            if self._has_audio(session_id) or not has_wavs:
                raise SessionExistsError(session_id)
            (folder / "session.json").unlink()  # the importer then takes only the audio
        store = SessionStore(folder.parent)
        extra = {} if self._free_space is None else {"free_space": self._free_space}
        importer = FolderImporter(
            folder.parent,
            FileSessionRepository(store),
            FileAudioStore(store, self._rate),
            self._repo,
            self._audio,
            self._rate,
            record_errors=False,
            **extra,
        )
        error = importer.import_one(session_id)
        if error is not None:
            raise BundleError(f"{error.reason}: {error.detail}")
        return ImportedSession(session_id, "audio_restored" if restore else "imported")

    def _exists(self, session_id: str) -> bool:
        try:
            self._repo.read_meta(session_id)
        except SessionNotFoundError:
            return False
        return True

    def _has_audio(self, session_id: str) -> bool:
        tracks = (AudioTrack(channel.value) for channel in Channel)
        return any(self._audio.track(session_id, track) is not None for track in tracks)
