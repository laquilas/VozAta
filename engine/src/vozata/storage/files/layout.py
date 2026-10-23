"""File names inside a session folder (architecture §8) and atomic file replacement."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vozata.domain import Channel

SESSION_ID = re.compile(r"^\d{8}_\d{6}(_[1-9]\d*)?$")


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
    def translated_jsonl(self) -> Path:
        return self.root / "transcript.translated.jsonl"

    @property
    def speakers_json(self) -> Path:
        return self.root / "speakers.json"

    @property
    def action_items_json(self) -> Path:
        return self.root / "action_items.json"

    @property
    def partial_minutes_json(self) -> Path:
        return self.root / "partial_minutes.json"  # phase 48


def write_atomic(target: Path, text: str) -> None:
    """Write `text` to a temp file in the same folder, then `os.replace` it onto `target`."""
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
