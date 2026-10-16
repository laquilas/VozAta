"""Mix the mic and system tracks into `mixed.wav`, streaming in blocks (`AudioMixer`)."""

from __future__ import annotations

import wave
from contextlib import ExitStack
from pathlib import Path

import numpy as np

_PCM_LIMIT = 32767


def _open_input(stack: ExitStack, path: Path) -> wave.Wave_read:
    wav = stack.enter_context(wave.open(str(path), "rb"))  # noqa: SIM115 (ExitStack closes it)
    if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
        raise ValueError(f"{path} must be mono 16-bit PCM")
    return wav


def _read_block(wav: wave.Wave_read, frames: int) -> np.ndarray:
    return np.frombuffer(wav.readframes(frames), dtype=np.int16)


class _BlockMixer:
    channels: int

    def __init__(self, block_seconds: float = 60) -> None:
        self._block_seconds = block_seconds

    def mix(self, mic: Path, system: Path, destination: Path) -> None:
        with ExitStack() as stack:
            mic_wav = _open_input(stack, mic)
            system_wav = _open_input(stack, system)
            rate = mic_wav.getframerate()
            if system_wav.getframerate() != rate:
                raise ValueError("mic and system tracks must share one sample rate")
            out = stack.enter_context(wave.open(str(destination), "wb"))
            out.setnchannels(self.channels)
            out.setsampwidth(2)
            out.setframerate(rate)
            block = max(1, round(self._block_seconds * rate))
            while True:
                left = _read_block(mic_wav, block)
                right = _read_block(system_wav, block)
                length = max(len(left), len(right))
                if length == 0:
                    break
                out.writeframes(self._combine(_pad(left, length), _pad(right, length)).tobytes())

    def _combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        raise NotImplementedError  # pragma: no cover


def _pad(samples: np.ndarray, length: int) -> np.ndarray:
    return np.pad(samples, (0, length - len(samples)))


class MonoMixer(_BlockMixer):
    """`MIX_MODE=mono`: sample-wise sum, hard-clipped to the 16-bit range."""

    channels = 1

    def _combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        total = mic.astype(np.int32) + system.astype(np.int32)
        return np.clip(total, -_PCM_LIMIT, _PCM_LIMIT).astype(np.int16)


class StereoMixer(_BlockMixer):
    """`MIX_MODE=stereo`: mic on the left channel, system on the right."""

    channels = 2

    def _combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        return np.column_stack((mic, system)).astype(np.int16).ravel()
