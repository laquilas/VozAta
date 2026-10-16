"""Domain types shared by every engine module (no I/O).

All times are seconds since session start.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np


class Channel(StrEnum):
    MIC = "mic"
    SYSTEM = "system"


class SessionStatus(StrEnum):
    RECORDING = "recording"
    PAUSED = "paused"
    FINALIZING = "finalizing"
    DONE = "done"
    INTERRUPTED = "interrupted"


class AppLanguage(StrEnum):
    EN = "en"
    PT_BR = "pt-BR"
    ES = "es"


class ConversationLanguage(StrEnum):
    EN = "en"
    PT = "pt"
    ES = "es"
    AUTO = "auto"


@dataclass(frozen=True, eq=False)
class AudioChunk:
    """Float32 mono samples at the session sample rate, starting at `start`."""

    channel: Channel
    start: float
    samples: np.ndarray


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    probability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "probability": self.probability,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Word:
        return cls(
            text=str(data["text"]),
            start=float(data["start"]),
            end=float(data["end"]),
            probability=float(data["probability"]),
        )


@dataclass(frozen=True)
class TranscriptionResult:
    """Words with chunk-relative timestamps; empty on silence."""

    words: tuple[Word, ...]
    language: str | None


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    channel: Channel
    speaker_id: str
    start: float
    end: float
    text: str
    words: tuple[Word, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to one `transcript.jsonl` line (architecture §8)."""
        return {
            "segment_id": self.segment_id,
            "channel": self.channel.value,
            "speaker_id": self.speaker_id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [word.to_dict() for word in self.words],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TranscriptSegment:
        return cls(
            segment_id=str(data["segment_id"]),
            channel=Channel(data["channel"]),
            speaker_id=str(data["speaker_id"]),
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data["text"]),
            words=tuple(Word.from_dict(word) for word in data.get("words", ())),
        )


def default_conversation_language(app_language: AppLanguage) -> ConversationLanguage:
    """The spoken language assumed when none is configured (`pt-BR` -> `pt`)."""
    return ConversationLanguage(app_language.value.split("-")[0])
