"""Session folders under `OUTPUT_DIR` and their metadata (architecture §8)."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import Channel, TranscriptSegment

_SESSION_ID = re.compile(r"^\d{8}_\d{6}(_[1-9]\d*)?$")


class SessionNotFoundError(LookupError):
    """No session with this id (or the id is not a session id)."""


@dataclass(frozen=True)
class SessionPaths:
    root: Path

    @property
    def id(self) -> str:
        return self.root.name

    @property
    def meta(self) -> Path:
        return self.root / "session.json"

    def wav(self, channel: Channel) -> Path:
        return self.root / f"{channel.value}.wav"

    @property
    def mixed_wav(self) -> Path:
        return self.root / "mixed.wav"

    @property
    def transcript_jsonl(self) -> Path:
        return self.root / "transcript.jsonl"

    @property
    def transcript_md(self) -> Path:
        return self.root / "transcript.md"

    @property
    def minutes_md(self) -> Path:
        return self.root / "minutes.md"

    @property
    def diarized_jsonl(self) -> Path:
        return self.root / "transcript.diarized.jsonl"

    @property
    def edited_jsonl(self) -> Path:
        return self.root / "transcript.edited.jsonl"


def _local_now() -> datetime:
    return datetime.now().astimezone()


class SessionStore:
    """Create, list and read session folders; `session.json` writes are atomic."""

    def __init__(self, output_dir: Path, now: Callable[[], datetime] = _local_now) -> None:
        self._root = output_dir
        self.now = now

    def create(self, started_at: datetime | None = None) -> SessionPaths:
        """A new, empty session folder named after the start time (default: now)."""
        base = (started_at or self.now()).strftime("%Y%m%d_%H%M%S")
        self._root.mkdir(parents=True, exist_ok=True)
        suffix = 1
        while True:
            session_id = base if suffix == 1 else f"{base}_{suffix}"
            try:
                (self._root / session_id).mkdir()
            except FileExistsError:
                suffix += 1
                continue
            return SessionPaths(self._root / session_id)

    def paths(self, session_id: str) -> SessionPaths:
        if not _SESSION_ID.match(session_id):
            raise SessionNotFoundError(session_id)
        return SessionPaths(self._root / session_id)

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        """Replace `session.json` atomically (temp file in the same folder + `os.replace`)."""
        target = self.paths(session_id).meta
        handle, temp = tempfile.mkstemp(dir=target.parent, prefix=".session-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
                json.dump(meta, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temp, target)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def read_meta(self, session_id: str) -> dict[str, Any]:
        path = self.paths(session_id).meta
        if not path.is_file():
            raise SessionNotFoundError(session_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[str]:
        """Ids of folders holding a `session.json`, newest first."""
        if not self._root.is_dir():
            return []
        ids = [
            item.name
            for item in self._root.iterdir()
            if _SESSION_ID.match(item.name) and (item / "session.json").is_file()
        ]
        return sorted(ids, reverse=True)

    def load_transcript(self, session_id: str) -> list[TranscriptSegment]:
        """The best transcript: edited, then diarized, then raw (empty when none exists)."""
        paths = self.paths(session_id)
        if not paths.root.is_dir():
            raise SessionNotFoundError(session_id)
        for path in (paths.edited_jsonl, paths.diarized_jsonl, paths.transcript_jsonl):
            if path.is_file():
                return _read_segments(path)
        return []

    def discard(self, session_id: str) -> None:
        """Delete a session folder (used when a recording fails to start)."""
        shutil.rmtree(self.paths(session_id).root)


def _read_segments(path: Path) -> list[TranscriptSegment]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [TranscriptSegment.from_dict(json.loads(line)) for line in lines if line.strip()]
