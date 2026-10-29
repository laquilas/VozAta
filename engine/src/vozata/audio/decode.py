"""`PyAvDecoder`: an audio or video file recorded elsewhere as the engine's PCM (phase 60).

PyAV (FFmpeg) comes with faster-whisper, so every format FFmpeg reads is accepted: wav, mp3, m4a,
aac, ogg, opus, flac, wma and the audio of mp4 / mkv / webm / mov. The first audio stream is
resampled to mono 16-bit at the engine's rate and streamed a frame at a time, so a long file is
never held in memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import av

from vozata.ports import AudioDecodeError


class PyAvDecoder:
    """`AudioDecoder` over PyAV."""

    def __init__(self, sample_rate: int) -> None:
        self._rate = sample_rate

    def duration(self, path: Path) -> float | None:
        try:
            with av.open(str(path)) as container:
                micros = container.duration  # in `av.time_base` units (microseconds)
        except (av.FFmpegError, OSError):
            return None
        return None if micros is None else micros / av.time_base

    def blocks(self, path: Path) -> Iterator[bytes]:
        try:
            container = av.open(str(path))
        except (av.FFmpegError, OSError) as error:
            raise AudioDecodeError(_reason(error)) from error
        with container:
            if not container.streams.audio:
                raise AudioDecodeError("no audio stream")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=self._rate)
            try:
                for frame in container.decode(stream):
                    yield from _pcm(resampler.resample(frame))
                yield from _pcm(resampler.resample(None))  # what the resampler still holds
            except av.FFmpegError as error:
                raise AudioDecodeError(_reason(error)) from error


def _reason(error: Exception) -> str:
    """FFmpeg's reason without the file's path: the path is the engine's temporary upload."""
    return getattr(error, "strerror", None) or type(error).__name__


def _pcm(frames: list[av.AudioFrame]) -> Iterator[bytes]:
    for frame in frames:
        block = frame.to_ndarray().tobytes()  # s16 mono: shape (1, samples)
        if block:
            yield block
