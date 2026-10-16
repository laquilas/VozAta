"""Cut a channel's audio into fixed transcription windows."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from vozata.domain import AudioChunk, Channel


class FixedWindowChunker:
    """Accumulate samples and emit an `AudioChunk` for every `chunk_seconds` window.

    Like the WAV writer, loopback gaps longer than `tolerance` are filled with silence, so chunk
    `start` values follow the session clock. Pausing emits the partial window and drops audio
    until resumed; windows then restart at the resume time.
    """

    def __init__(
        self,
        channel: Channel,
        chunk_seconds: float,
        sample_rate: int,
        on_chunk: Callable[[AudioChunk], None],
        tolerance: float = 0.15,
    ) -> None:
        self._channel = channel
        self._rate = sample_rate
        self._window = round(chunk_seconds * sample_rate)
        self._tolerance = round(tolerance * sample_rate)
        self._on_chunk = on_chunk
        self._blocks: list[np.ndarray] = []
        self._buffered = 0
        self._position = 0  # session sample index just after the last accepted sample
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        if value and not self._paused:
            self.flush()
        self._paused = value

    def feed(self, samples: np.ndarray, at: float) -> None:
        """Accept a block whose first sample belongs at session time `at`."""
        start = round(at * self._rate)
        if self._paused:
            self._position = max(self._position, start + len(samples))
            return
        gap = start - self._position
        if gap > self._tolerance:
            self._append(np.zeros(gap, dtype=np.float32))
        self._append(samples)
        while self._buffered >= self._window:
            self._emit(self._window)

    def flush(self) -> None:
        """Emit the partial window, if any."""
        if self._buffered:
            self._emit(self._buffered)

    def _append(self, samples: np.ndarray) -> None:
        self._blocks.append(samples.astype(np.float32, copy=False))
        self._buffered += len(samples)
        self._position += len(samples)

    def _emit(self, count: int) -> None:
        buffer = np.concatenate(self._blocks)
        start = (self._position - self._buffered) / self._rate
        self._on_chunk(AudioChunk(channel=self._channel, start=start, samples=buffer[:count]))
        rest = buffer[count:]
        self._blocks = [rest] if len(rest) else []
        self._buffered = len(rest)
