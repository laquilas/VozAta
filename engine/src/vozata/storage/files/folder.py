"""A session folder named on the command line (`minutes`, `diarize`) in the file backend of its
parent folder, and the files those commands report."""

from __future__ import annotations

from pathlib import Path

from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.layout import SessionPaths
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_folder import SessionFolder
from vozata.storage.session_store import SessionStore


def open_session_folder(session_dir: Path, sample_rate: int) -> SessionFolder:
    """Nothing is read yet: an unknown folder raises `SessionNotFoundError` on first use."""
    path = session_dir.resolve()
    store = SessionStore(path.parent)
    paths = SessionPaths(path)
    return SessionFolder(
        path,
        FileSessionRepository(store),
        FileAudioStore(store, sample_rate),
        paths.minutes_md,
        paths.diarized_jsonl,
    )
