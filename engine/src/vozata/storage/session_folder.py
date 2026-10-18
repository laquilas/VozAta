"""A session folder named on the command line (`minutes`, `diarize`) and where it is stored."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vozata.ports import SessionAudio, SessionRepository


@dataclass(frozen=True)
class SessionFolder:
    """`path` (absolute) is `OUTPUT_DIR/<id>`; the repository and audio store of its parent hold
    the session. `minutes_file` / `diarized_file` are what the commands report as written (the
    file backend's files, or the SQLite database)."""

    path: Path
    repository: SessionRepository
    audio: SessionAudio
    minutes_file: Path
    diarized_file: Path

    @property
    def session_id(self) -> str:
        return self.path.name
