"""Playable PCM tracks and the generated WAV header (phase 32)."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from tests.fakes import FakeAudioReader
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.audio.pcm import ChannelTrack, MixedTrack, wav_header, wav_size, write_wav
from vozata.domain import Channel


@pytest.mark.parametrize(("rate", "channels", "frames"), [(16000, 1, 0), (48000, 2, 12345)])
def test_the_header_matches_the_wave_module(rate: int, channels: int, frames: int) -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames * channels * 2))

    assert wav_header(rate, channels, frames) == buffer.getvalue()[:44]


def test_a_channel_track_reads_its_range_as_little_endian_bytes() -> None:
    reader = FakeAudioReader({Channel.MIC: np.array([1, -2, 3], np.int16)}, {Channel.MIC: 8000})

    track = ChannelTrack(reader, "s", Channel.MIC)

    assert (track.rate, track.channels, track.frames) == (8000, 1, 3)
    assert track.read(1, 10) == np.array([-2, 3], "<i2").tobytes()
    assert track.read(3, 1) == b""
    assert track.read(-1, 2) == b""


def test_the_mixed_track_pads_the_shorter_channel() -> None:
    reader = FakeAudioReader(
        {Channel.MIC: np.array([1, 2, 3], np.int16), Channel.SYSTEM: np.array([10], np.int16)}
    )

    mono = MixedTrack(reader, "s", MonoMixer())
    stereo = MixedTrack(reader, "s", StereoMixer())

    assert np.frombuffer(mono.read(0, 5), "<i2").tolist() == [11, 2, 3]
    assert np.frombuffer(stereo.read(1, 5), "<i2").tolist() == [2, 0, 3, 0]
    assert (stereo.channels, stereo.frames) == (2, 3)
    assert mono.read(3, 2) == b""


def test_the_mixed_track_needs_one_sample_rate() -> None:
    reader = FakeAudioReader(
        {Channel.MIC: np.zeros(2, np.int16), Channel.SYSTEM: np.zeros(2, np.int16)},
        {Channel.MIC: 16000, Channel.SYSTEM: 48000},
    )

    with pytest.raises(ValueError, match="one sample rate"):
        MixedTrack(reader, "s", MonoMixer())


def test_write_wav_writes_a_readable_file_of_the_announced_size() -> None:
    samples = np.arange(25, dtype=np.int16)
    reader = FakeAudioReader({Channel.SYSTEM: samples}, {Channel.SYSTEM: 2})
    track = ChannelTrack(reader, "s", Channel.SYSTEM)
    out = io.BytesIO()

    write_wav(track, out)

    assert len(out.getvalue()) == wav_size(track)
    with wave.open(io.BytesIO(out.getvalue()), "rb") as wav:
        assert np.frombuffer(wav.readframes(100), "<i2").tolist() == samples.tolist()
