"""Reading a whole session folder for the import of phase 33, strictly: what the file backend
skips with a warning (an unreadable line or action-items file) is an error here."""

from __future__ import annotations

import json
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import ActionItem, PartialMinutes, TranscriptSegment, Translation
from vozata.ports import StoreRepairError
from vozata.storage.files.layout import SessionPaths
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import read_segments

BAD_JSON = (ValueError, KeyError, TypeError)  # json.JSONDecodeError is a ValueError
_BAD_WAV = (wave.Error, EOFError, OSError, StoreRepairError)


class FolderError(Exception):
    """A folder that cannot be imported; `reason` is a `[migration]` locale key."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class FolderContent:
    """Everything of a session folder but its metadata and audio."""

    segments: dict[str, list[TranscriptSegment]]  # by source: raw, diarized, edited
    translations: dict[str, Translation]
    speakers: list[str]
    names: dict[str, str]
    minutes: tuple[str, datetime] | None  # markdown and when it was written
    action_items: list[ActionItem]
    partial_minutes: list[PartialMinutes] = field(default_factory=list)  # phase 48


def read_meta(files: FileSessionRepository, session_id: str) -> dict[str, Any]:
    try:
        meta = files.read_meta(session_id)
        if not isinstance(meta, dict):
            raise TypeError("session.json is not an object")
    except BAD_JSON as error:
        raise FolderError("unreadable_json", f"session.json: {error}") from error
    return meta


def read_content(files: FileSessionRepository, paths: SessionPaths) -> FolderContent:
    """Raises `FolderError` (`unreadable_json`)."""
    try:
        segments = {
            source: read_segments(path) if path.is_file() else []
            for source, path in (
                ("raw", paths.transcript_jsonl),
                ("diarized", paths.diarized_jsonl),
                ("edited", paths.edited_jsonl),
            )
        }
        items: list[ActionItem] = []
        if paths.action_items_json.is_file():
            data = json.loads(paths.action_items_json.read_text(encoding="utf-8"))
            items = [ActionItem.from_dict(item) for item in data["items"]]
    except BAD_JSON as error:
        raise FolderError("unreadable_json", str(error)) from error
    minutes = None
    if paths.minutes_md.is_file():
        written = datetime.fromtimestamp(paths.minutes_md.stat().st_mtime).astimezone()
        minutes = (paths.minutes_md.read_text(encoding="utf-8"), written)
    return FolderContent(
        segments=segments,
        translations=files.load_translations(paths.id),
        speakers=files.store.speaker_ids(paths.id),
        names=files.speaker_names(paths.id),
        minutes=minutes,
        action_items=items,
        partial_minutes=files.read_partial_minutes(paths.id),
    )


def wav_blocks(path: Path, rate: int) -> Iterator[bytes]:
    """The samples of a mono 16-bit WAV at `rate`, one second per block; raises `FolderError`
    (`unsupported_wav` for another format, `unreadable_wav`)."""
    try:
        with wave.open(str(path), "rb") as wav:
            shape = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            if shape != (1, 2, rate):
                raise FolderError("unsupported_wav", f"{path.name}: {shape} is not (1, 2, {rate})")
            while block := wav.readframes(rate):
                yield block
    except _BAD_WAV as error:
        raise FolderError("unreadable_wav", f"{path.name}: {error}") from error
