"""Session folders under `OUTPUT_DIR` and their metadata (architecture §8)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import Channel, TranscriptSegment

_log = logging.getLogger(__name__)
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

    @property
    def speakers_json(self) -> Path:
        return self.root / "speakers.json"


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
        _write_atomic(target, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

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
        return self.load_transcript_with_source(session_id)[1]

    def load_transcript_with_source(self, session_id: str) -> tuple[str, list[TranscriptSegment]]:
        """The best transcript and its source: `edited`, `diarized` or `raw`."""
        paths = self.paths(session_id)
        if not paths.root.is_dir():
            raise SessionNotFoundError(session_id)
        for source, path in (
            ("edited", paths.edited_jsonl),
            ("diarized", paths.diarized_jsonl),
            ("raw", paths.transcript_jsonl),
        ):
            if path.is_file():
                return source, _read_segments(path)
        return "raw", []

    def load_raw_transcript(self, session_id: str) -> list[TranscriptSegment]:
        """`transcript.jsonl` as captured (empty when it does not exist)."""
        path = self.paths(session_id).transcript_jsonl
        return _read_segments(path) if path.is_file() else []

    def write_diarized(self, session_id: str, segments: list[TranscriptSegment]) -> None:
        """Replace `transcript.diarized.jsonl` atomically (phase 14)."""
        lines = "".join(
            json.dumps(segment.to_dict(), ensure_ascii=False) + "\n" for segment in segments
        )
        _write_atomic(self.paths(session_id).diarized_jsonl, lines)

    def write_speakers(self, session_id: str, speaker_ids: list[str]) -> None:
        """Replace `speakers.json` with these ids and no names (`{"system:1": {"name": null}}`)."""
        speakers = {speaker_id: {"name": None} for speaker_id in speaker_ids}
        text = json.dumps(speakers, ensure_ascii=False, indent=2) + "\n"
        _write_atomic(self.paths(session_id).speakers_json, text)

    def speaker_names(self, session_id: str) -> dict[str, str]:
        """Names given to speakers in `speakers.json` (empty when absent or unreadable)."""
        speakers = _read_speakers(self.paths(session_id).speakers_json)
        return {
            speaker_id: entry["name"]
            for speaker_id, entry in speakers.items()
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }

    def rename_speakers(self, session_id: str, names: Mapping[str, str | None]) -> None:
        """Merge trimmed names into `speakers.json` (phase 16); an empty name clears it."""
        path = self.paths(session_id).speakers_json
        speakers = _read_speakers(path)
        for speaker_id, name in names.items():
            entry = speakers.get(speaker_id)
            entry = dict(entry) if isinstance(entry, dict) else {}
            entry["name"] = (name or "").strip() or None
            speakers[speaker_id] = entry
        _write_atomic(path, json.dumps(speakers, ensure_ascii=False, indent=2) + "\n")

    def discard(self, session_id: str) -> None:
        """Delete a session folder (used when a recording fails to start)."""
        shutil.rmtree(self.paths(session_id).root)


def _write_atomic(target: Path, text: str) -> None:
    """Write `text` to a temp file in the same folder, then `os.replace` it onto `target`."""
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _read_speakers(path: Path) -> dict[str, Any]:
    """`speakers.json` as a dict (empty when absent or unreadable)."""
    if not path.is_file():
        return {}
    try:
        speakers = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        speakers = None
    if not isinstance(speakers, dict):
        _log.warning("Ignoring unreadable %s", path)
        return {}
    return {str(speaker_id): entry for speaker_id, entry in speakers.items()}


def _read_segments(path: Path) -> list[TranscriptSegment]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [TranscriptSegment.from_dict(json.loads(line)) for line in lines if line.strip()]
