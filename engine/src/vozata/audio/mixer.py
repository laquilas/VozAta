"""Mix the mic and system tracks into one WAV, streaming in blocks (`AudioMixer`).

The tracks are read through an `AudioReader`, so the mixer works on any storage backend.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from vozata.domain import Channel
from vozata.ports import AudioReader

_PCM_LIMIT = 32767


class _BlockMixer:
    channels: int

    def __init__(self, block_seconds: float = 60) -> None:
        self._block_seconds = block_seconds

    def mix(self, reader: AudioReader, session_id: str, destination: Path) -> None:
        rate = reader.sample_rate(session_id, Channel.MIC)
        if reader.sample_rate(session_id, Channel.SYSTEM) != rate:
            raise ValueError("mic and system tracks must share one sample rate")
        total = max(reader.length(session_id, channel) for channel in (Channel.MIC, Channel.SYSTEM))
        block = max(1, round(self._block_seconds * rate))
        with wave.open(str(destination), "wb") as out:
            out.setnchannels(self.channels)
            out.setsampwidth(2)
            out.setframerate(rate)
            for start in range(0, total, block):
                left = reader.frames(session_id, Channel.MIC, start, block)
                right = reader.frames(session_id, Channel.SYSTEM, start, block)
                length = max(len(left), len(right))
                out.writeframes(self.combine(_pad(left, length), _pad(right, length)).tobytes())

    def combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        raise NotImplementedError  # pragma: no cover


def _pad(samples: np.ndarray, length: int) -> np.ndarray:
    return np.pad(samples, (0, length - len(samples)))


class MonoMixer(_BlockMixer):
    """`MIX_MODE=mono`: sample-wise sum, hard-clipped to the 16-bit range."""

    channels = 1

    def combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        total = mic.astype(np.int32) + system.astype(np.int32)
        return np.clip(total, -_PCM_LIMIT, _PCM_LIMIT).astype(np.int16)


class StereoMixer(_BlockMixer):
    """`MIX_MODE=stereo`: mic on the left channel, system on the right."""

    channels = 2

    def combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        return np.column_stack((mic, system)).astype(np.int16).ravel()
