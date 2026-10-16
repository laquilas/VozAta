"""Shared fakes for the engine ports (no hardware, GPU, network or real LLM)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

from vozata.domain import (
    Channel,
    ConversationLanguage,
    SessionStatus,
    TranscriptionResult,
    TranscriptSegment,
)


class FakeAudioSource:
    """Delivers pre-recorded blocks when started; `push` delivers more while running."""

    def __init__(self, blocks: list[tuple[np.ndarray, float]] | None = None) -> None:
        self.blocks = blocks or []
        self.started = False
        self.stopped = False
        self._on_samples: Callable[[np.ndarray, float], None] | None = None

    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        self.started = True
        self._on_samples = on_samples
        for samples, at in self.blocks:
            on_samples(samples, at)

    def push(self, samples: np.ndarray, at: float) -> None:
        if self._on_samples is None:
            raise RuntimeError("FakeAudioSource.push() before start()")
        self._on_samples(samples, at)

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
    """Returns queued results in order, then empty results; pure silence is always empty."""

    def __init__(self, results: list[TranscriptionResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[np.ndarray, str | None, str | None]] = []
        self.closed = False

    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None = None
    ) -> TranscriptionResult:
        self.calls.append((samples, language, hints))
        if self.results and np.any(samples):
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
        self.releases = 0

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.prompts.append((system, prompt, json_schema))
        return self.replies.pop(0) if self.replies else ""

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        yield from self.generate(system, prompt).split(" ")

    def is_available(self) -> bool:
        return self.available

    def release(self) -> None:
        self.releases += 1


class FakeSpeechDetector:
    """Every non-zero sample is speech; spans are runs of them, in seconds. Counts calls."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.calls: list[int] = []  # length of every analysed buffer

    def speech_spans(self, samples: np.ndarray) -> list[tuple[float, float]]:
        self.calls.append(len(samples))
        voiced = np.concatenate(([0], (samples != 0).astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(voiced))
        return [
            (start / self.sample_rate, end / self.sample_rate)
            for start, end in zip(edges[::2], edges[1::2], strict=True)
        ]


class FakeLocalizer:
    """Echoes the key with its params, e.g. `labels.user(n=2)`."""

    def t(self, key: str, /, **params: object) -> str:
        if not params:
            return key
        args = ",".join(f"{name}={value}" for name, value in sorted(params.items()))
        return f"{key}({args})"


class FakeClock:
    """A session clock the test moves by hand."""

    def __init__(self) -> None:
        self.started = False
        self.time = 0.0

    def start(self) -> None:
        self.started = True

    def now(self) -> float:
        return self.time


class FakeSessionObserver:
    """Records every event as `(name, *args)`; `segments` and `errors` for quick asserts."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_status(self, status: SessionStatus, duration_seconds: float) -> None:
        self.events.append(("status", status, duration_seconds))

    def on_level(self, channel: Channel, rms_db: float) -> None:
        self.events.append(("level", channel, rms_db))

    def on_segment(self, segment: TranscriptSegment) -> None:
        self.events.append(("segment", segment))

    def on_language_detected(self, language: ConversationLanguage) -> None:
        self.events.append(("language_detected", language))

    def on_minutes_ready(self, session_id: str) -> None:
        self.events.append(("minutes_ready", session_id))

    def on_error(self, code: str, message: str) -> None:
        self.events.append(("error", code, message))

    def of(self, name: str) -> list[tuple]:
        return [event[1:] for event in self.events if event[0] == name]
