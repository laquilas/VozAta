"""Domain types shared by every engine module (no I/O).

All times are seconds since session start.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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


class ChunkMode(StrEnum):
    VAD = "vad"  # cut at pauses (phase 27)
    FIXED = "fixed"  # CHUNK_SECONDS windows


class MixMode(StrEnum):
    MONO = "mono"
    STEREO = "stereo"


class WhisperDevice(StrEnum):
    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


@dataclass(frozen=True, eq=False)
class AudioChunk:
    """Float32 mono samples at the session sample rate, starting at `start`.

    `complete` chunks end in a pause (VAD cut): the stitcher commits all of their words.
    """

    channel: Channel
    start: float
    samples: np.ndarray
    complete: bool = False


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
    edited: bool = False  # the user changed the text (phase 21); `words` is then empty

    def to_dict(self) -> dict[str, Any]:
        """Serialize to one `transcript.jsonl` line (architecture §8).

        `"edited": true` is written only for user-edited segments, so raw lines keep their schema.
        """
        data: dict[str, Any] = {
            "segment_id": self.segment_id,
            "channel": self.channel.value,
            "speaker_id": self.speaker_id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [word.to_dict() for word in self.words],
        }
        if self.edited:
            data["edited"] = True
        return data

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
            edited=bool(data.get("edited", False)),
        )


@dataclass(frozen=True)
class SpeakerTurn:
    """A span of `system.wav` where one remote speaker talks (diarization, phase 14).

    `speaker_index` is the diarizer's own numbering; `assign_speakers` renumbers by first
    appearance in the transcript.
    """

    start: float
    end: float
    speaker_index: int

    def overlap(self, start: float, end: float) -> float:
        """Seconds this turn shares with the span `start`-`end` (0 when they do not meet)."""
        return max(0.0, min(self.end, end) - max(self.start, start))


def default_conversation_language(app_language: AppLanguage) -> ConversationLanguage:
    """The spoken language assumed when none is configured (`pt-BR` -> `pt`)."""
    return ConversationLanguage(app_language.value.split("-")[0])


# Document export (phase 11): built by `export.document`, rendered by `DocumentExporter`s.


@dataclass(frozen=True)
class Block:
    """One block of the minutes: `h1`-`h3`, `p`, `bullet` or `numbered` (text includes "1.")."""

    kind: str
    text: str


@dataclass(frozen=True)
class Row:
    """One transcript line: `hh:mm:ss`, speaker label, text."""

    time: str
    speaker: str
    text: str


@dataclass(frozen=True)
class ExportDocument:
    title: str
    details: list[str]
    minutes_title: str
    minutes_markdown: str | None
    minutes_blocks: list[Block]
    no_minutes: str
    transcript_title: str
    columns: tuple[str, str, str]
    rows: list[Row] = field(default_factory=list)


# Cross-session search (phase 22).

SNIPPET_START = "\x02"  # marks where a matched term starts in `SearchHit.snippet`
SNIPPET_END = "\x03"  # ... and where it ends


@dataclass(frozen=True)
class SearchHit:
    """One transcript segment matching a search; `snippet` wraps matches in the markers above."""

    session_id: str
    segment_id: str
    start: float
    speaker_id: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "segment_id": self.segment_id,
            "start": self.start,
            "speaker_id": self.speaker_id,
            "snippet": self.snippet,
        }


# Ask the meeting (phase 24).


@dataclass(frozen=True)
class Citation:
    """A transcript segment an answer cites, as `[session_id@hh:mm:ss]` in the answer text."""

    session_id: str
    segment_id: str
    start: float

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "segment_id": self.segment_id, "start": self.start}
