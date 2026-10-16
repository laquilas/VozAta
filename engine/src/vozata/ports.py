"""Ports: the interfaces orchestrators depend on (architecture §5).

Concrete implementations are wired only in `bootstrap.py`. Ports are added by the phase that first
needs them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from vozata.domain import (
    Channel,
    ConversationLanguage,
    SessionStatus,
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
class AudioMixer(Protocol):
    def mix(self, mic: Path, system: Path, destination: Path) -> None: ...


class LanguageModelError(RuntimeError):
    """A language model could not produce a reply (unreachable, failed or malformed)."""


@runtime_checkable
class LanguageModel(Protocol):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str: ...

    def stream(self, system: str, prompt: str) -> Iterator[str]: ...

    def is_available(self) -> bool: ...


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

    def on_error(self, code: str, message: str) -> None:
        """A non-fatal error; `message` is localized."""
        ...
