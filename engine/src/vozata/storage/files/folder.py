"""A session folder named on the command line (`minutes`, `diarize`): the file backend of its
parent folder, and the files those commands report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


@dataclass(frozen=True)
class SessionFolder:
    path: Path  # absolute
    repository: FileSessionRepository
    audio: FileAudioStore

    @property
    def session_id(self) -> str:
        return self.path.name

    @property
    def minutes_file(self) -> Path:
        return self.repository.paths(self.session_id).minutes_md

    @property
    def diarized_file(self) -> Path:
        return self.repository.paths(self.session_id).diarized_jsonl


def open_session_folder(session_dir: Path, sample_rate: int) -> SessionFolder:
    """Nothing is read yet: an unknown folder raises `SessionNotFoundError` on first use."""
    path = session_dir.resolve()
    store = SessionStore(path.parent)
    return SessionFolder(path, FileSessionRepository(store), FileAudioStore(store, sample_rate))
