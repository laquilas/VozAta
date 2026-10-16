"""Shared fakes for the engine ports (no hardware, GPU, network or real LLM)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

from vozata.domain import TranscriptionResult, TranscriptSegment


class FakeAudioSource:
    """Delivers pre-recorded blocks when started."""

    def __init__(self, blocks: list[tuple[np.ndarray, float]] | None = None) -> None:
        self.blocks = blocks or []
        self.started = False
        self.stopped = False

    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        self.started = True
        for samples, at in self.blocks:
            on_samples(samples, at)

    def stop(self) -> None:
        self.stopped = True


class FakeAudioSink:
    def __init__(self) -> None:
        self.writes: list[tuple[np.ndarray, float]] = []
        self.finalized_at: float | None = None

    def write(self, samples: np.ndarray, at: float) -> None:
        self.writes.append((samples, at))

    def finalize(self, total_seconds: float) -> None:
        self.finalized_at = total_seconds


class FakeTranscriber:
    """Returns queued results in order, then empty results."""

    def __init__(self, results: list[TranscriptionResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[np.ndarray, str | None, str | None]] = []
        self.closed = False

    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None = None
    ) -> TranscriptionResult:
        self.calls.append((samples, language, hints))
        if self.results:
            return self.results.pop(0)
        return TranscriptionResult(words=(), language=language)

    def close(self) -> None:
        self.closed = True


class FakeTranscriptSink:
    def __init__(self) -> None:
        self.segments: list[TranscriptSegment] = []
        self.closed = False

    def emit(self, segment: TranscriptSegment) -> None:
        self.segments.append(segment)

    def close(self) -> None:
        self.closed = True


class FakeAudioMixer:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, Path]] = []

    def mix(self, mic: Path, system: Path, destination: Path) -> None:
        self.calls.append((mic, system, destination))


class FakeLanguageModel:
    """Returns canned replies in order; records every prompt."""

    def __init__(self, replies: list[str] | None = None, available: bool = True) -> None:
        self.replies = list(replies or [])
        self.available = available
        self.prompts: list[tuple[str, str, dict | None]] = []

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.prompts.append((system, prompt, json_schema))
        return self.replies.pop(0) if self.replies else ""

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        yield from self.generate(system, prompt).split(" ")

    def is_available(self) -> bool:
        return self.available


class FakeLocalizer:
    """Echoes the key with its params, e.g. `labels.user(n=2)`."""

    def t(self, key: str, **params: object) -> str:
        if not params:
            return key
        args = ",".join(f"{name}={value}" for name, value in sorted(params.items()))
        return f"{key}({args})"
