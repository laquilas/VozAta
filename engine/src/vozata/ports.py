"""Ports: the interfaces orchestrators depend on (architecture §5).

Concrete implementations are wired only in `bootstrap.py`. Ports are added by the phase that first
needs them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from vozata.domain import (
    AudioChunk,
    Channel,
    ConversationLanguage,
    ExportDocument,
    SearchHit,
    SessionStatus,
    SpeakerTurn,
    TranscriptionResult,
    TranscriptSegment,
)


@runtime_checkable
class AudioSource(Protocol):
    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        """Begin delivering float32 mono samples with their session time."""
        ...

    def stop(self) -> None: ...


@runtime_checkable
class AudioSink(Protocol):
    def write(self, samples: np.ndarray, at: float) -> None: ...

    def finalize(self, total_seconds: float) -> None: ...


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None = None
    ) -> TranscriptionResult:
        """Return chunk-relative words; an empty result on silence (never raise for silence)."""
        ...

    def close(self) -> None:
        """Release model memory (GPU)."""
        ...


@runtime_checkable
class TranscriptSink(Protocol):
    def emit(self, segment: TranscriptSegment) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class Chunker(Protocol):
    """Cuts one channel's captured audio into `AudioChunk`s (fixed windows or pauses)."""

    paused: bool  # pausing emits the buffered audio and drops audio until resumed

    def feed(self, samples: np.ndarray, at: float) -> None: ...

    def flush(self) -> None: ...

    def buffered(self) -> AudioChunk | None:
        """A copy of the audio not emitted yet (interim text, phase 28)."""
        ...


@runtime_checkable
class SpeechDetector(Protocol):
    def speech_spans(self, samples: np.ndarray) -> list[tuple[float, float]]:
        """Unpadded (start, end) seconds of speech in `samples`, in order."""
        ...


@runtime_checkable
class AudioMixer(Protocol):
    def mix(self, mic: Path, system: Path, destination: Path) -> None: ...


class LanguageModelError(RuntimeError):
    """A language model could not produce a reply (unreachable, failed or malformed)."""


@runtime_checkable
class LanguageModel(Protocol):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str: ...

    def stream(self, system: str, prompt: str) -> Iterator[str]: ...

    def is_available(self) -> bool: ...

    def release(self) -> None:
        """Free the model's memory (VRAM) after a job; raises `LanguageModelError` on failure."""
        ...


class DiarizationError(RuntimeError):
    """Speaker identification failed (missing extra or token, model error, bad output)."""


@runtime_checkable
class Diarizer(Protocol):
    """Finds who speaks when in a recording (phase 14); only `system.wav` is diarized."""

    def diarize(
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        """Speaker turns in time order; raises `DiarizationError` on failure."""
        ...

    def close(self) -> None:
        """Release model memory (GPU)."""
        ...


@runtime_checkable
class DocumentExporter(Protocol):
    """Renders an `ExportDocument` (minutes + transcript) as one file format (phase 11)."""

    media_type: str
    extension: str

    def export(self, document: ExportDocument) -> bytes: ...


@runtime_checkable
class Localizer(Protocol):
    def t(self, key: str, /, **params: object) -> str: ...


@runtime_checkable
class SessionObserver(Protocol):
    """Receives recording-session events (console in phase 05, WebSocket in phase 06).

    Calls arrive from capture and transcription threads; implementations must be thread-safe and
    return quickly.
    """

    def on_status(self, status: SessionStatus, duration_seconds: float) -> None: ...

    def on_level(self, channel: Channel, rms_db: float) -> None: ...

    def on_segment(self, segment: TranscriptSegment) -> None: ...

    def on_language_detected(self, language: ConversationLanguage) -> None: ...

    def on_minutes_ready(self, session_id: str) -> None: ...

    def on_partial(self, channel: Channel, speaker_id: str, start: float, text: str) -> None:
        """Interim text of a channel (phase 28); empty `text` clears it. Never written to files."""
        ...

    def on_model_loading(self, loading: bool) -> None:
        """The speech model started (True) or finished (False) loading; capture already runs."""
        ...

    def on_error(self, code: str, message: str) -> None:
        """A non-fatal error; `message` is localized."""
        ...


@runtime_checkable
class TranscriptSearch(Protocol):
    """Full-text search over every session's transcript (phase 22; reused by 21 and 24)."""

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        """Replace everything indexed for `session_id` with `segments`."""
        ...

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        """Best matches first for free user text; FTS syntax in `query` is never interpreted."""
        ...
