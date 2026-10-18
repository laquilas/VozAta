"""Playable PCM tracks (`PcmTrack`, phase 32): a channel of an `AudioReader`, the mic + system
mix computed on read, and the WAV header that turns a track into a file or an HTTP stream."""

from __future__ import annotations

import struct
from typing import BinaryIO

import numpy as np

from vozata.domain import Channel
from vozata.ports import AudioMixer, AudioReader, PcmTrack

SAMPLE_WIDTH = 2  # bytes: 16-bit PCM
WAV_HEADER_BYTES = 44
COPY_SECONDS = 10  # frames per read when a track is copied to a file


def wav_header(rate: int, channels: int, frames: int) -> bytes:
    """The 44-byte header of a PCM WAV holding `frames` frames."""
    block = channels * SAMPLE_WIDTH
    data = frames * block
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, 8 * SAMPLE_WIDTH)
        + b"data"
        + struct.pack("<I", data)
    )


def wav_size(track: PcmTrack) -> int:
    """The size in bytes of `track` as a WAV file."""
    return WAV_HEADER_BYTES + track.frames * track.channels * SAMPLE_WIDTH


def write_wav(track: PcmTrack, out: BinaryIO) -> None:
    """Write `track` as a WAV file to `out`, a few seconds at a time."""
    out.write(wav_header(track.rate, track.channels, track.frames))
    block = max(1, track.rate * COPY_SECONDS)
    for start in range(0, track.frames, block):
        out.write(track.read(start, block))


class ChannelTrack:
    """One channel of an `AudioReader` (mono)."""

    channels = 1

    def __init__(self, reader: AudioReader, session_id: str, channel: Channel) -> None:
        self._reader = reader
        self._id = session_id
        self._channel = channel
        self.rate = reader.sample_rate(session_id, channel)
        self.frames = reader.length(session_id, channel)

    def read(self, start: int, count: int) -> bytes:
        count = min(count, self.frames - start)
        if start < 0 or count <= 0:
            return b""
        return self._reader.frames(self._id, self._channel, start, count).astype("<i2").tobytes()


class MixedTrack:
    """The mic and system channels mixed on read by `mixer` (never stored); the shorter
    channel is padded with silence."""

    def __init__(self, reader: AudioReader, session_id: str, mixer: AudioMixer) -> None:
        self._reader = reader
        self._id = session_id
        self._mixer = mixer
        self.channels = mixer.channels
        self.rate = reader.sample_rate(session_id, Channel.MIC)
        if reader.sample_rate(session_id, Channel.SYSTEM) != self.rate:
            raise ValueError("mic and system tracks must share one sample rate")
        self.frames = max(reader.length(session_id, channel) for channel in Channel)

    def read(self, start: int, count: int) -> bytes:
        count = min(count, self.frames - start)
        if start < 0 or count <= 0:
            return b""
        mic = _padded(self._reader.frames(self._id, Channel.MIC, start, count), count)
        system = _padded(self._reader.frames(self._id, Channel.SYSTEM, start, count), count)
        return self._mixer.combine(mic, system).astype("<i2").tobytes()


def _padded(samples: np.ndarray, length: int) -> np.ndarray:
    return np.pad(samples, (0, length - len(samples)))
