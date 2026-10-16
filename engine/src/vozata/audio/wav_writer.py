"""WAV writer aligned to the session clock (`AudioSink`)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    """Float samples in [-1, 1] to 16-bit PCM, clipping out-of-range values."""
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)


class AlignedWavWriter:
    """Mono 16-bit WAV whose sample index tracks session time.

    Windows loopback delivers no data while nothing plays; when a block starts more than
    `tolerance` seconds after the audio written so far, the gap is filled with silence so every
    track of a session stays aligned. While `paused`, blocks are written as silence.
    """

    def __init__(self, path: Path, sample_rate: int, tolerance: float = 0.15) -> None:
        self._rate = sample_rate
        self._tolerance = round(tolerance * sample_rate)
        # Long-lived handle: stays open across writes until finalize().
        self._wav: wave.Wave_write | None = wave.open(str(path), "wb")  # noqa: SIM115
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)
        self.samples_written = 0
        self.paused = False

    def write(self, samples: np.ndarray, at: float) -> None:
        """Write a block whose first sample belongs at session time `at`."""
        expected = round(at * self._rate)
        if expected - self.samples_written > self._tolerance:
            self._append(np.zeros(expected - self.samples_written, dtype=np.float32))
        self._append(np.zeros_like(samples) if self.paused else samples)

    def finalize(self, total_seconds: float) -> None:
        """Pad with silence up to `total_seconds` (never truncate) and close the file."""
        if self._wav is None:
            return
        missing = round(total_seconds * self._rate) - self.samples_written
        if missing > 0:
            self._append(np.zeros(missing, dtype=np.float32))
        self._wav.close()
        self._wav = None

    def _append(self, samples: np.ndarray) -> None:
        if self._wav is None:
            raise RuntimeError("AlignedWavWriter is already finalized")
        self._wav.writeframes(to_pcm16(samples).tobytes())
        self.samples_written += len(samples)
