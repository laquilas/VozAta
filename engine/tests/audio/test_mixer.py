from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioReader
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.domain import Channel
from vozata.ports import AudioMixer

RATE = 100
SESSION = "20261015_202358"


def _reader(mic: list[int], system: list[int], system_rate: int = RATE) -> FakeAudioReader:
    return FakeAudioReader(
        {Channel.MIC: np.array(mic), Channel.SYSTEM: np.array(system)},
        {Channel.MIC: RATE, Channel.SYSTEM: system_rate},
    )


def _read(path: Path) -> tuple[int, int, list[int]]:
    with wave.open(str(path), "rb") as wav:
        frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        return wav.getnchannels(), wav.getframerate(), frames.tolist()


@pytest.fixture
def tracks(tmp_path: Path) -> tuple[FakeAudioReader, Path]:
    return _reader([100, -200, 30000, -30000, 5], [1, 2, 30000, -30000]), tmp_path / "mixed.wav"


@pytest.mark.parametrize("mixer", [MonoMixer(), StereoMixer()])
def test_mixers_satisfy_the_port(mixer: object) -> None:
    assert isinstance(mixer, AudioMixer)


def test_mono_mix_sums_samples_and_clips(tracks: tuple[FakeAudioReader, Path]) -> None:
    reader, mixed = tracks

    MonoMixer().mix(reader, SESSION, mixed)

    assert _read(mixed) == (1, RATE, [101, -198, 32767, -32767, 5])


def test_stereo_mix_puts_mic_left_and_system_right(tracks: tuple[FakeAudioReader, Path]) -> None:
    reader, mixed = tracks

    StereoMixer().mix(reader, SESSION, mixed)

    channels, rate, frames = _read(mixed)
    assert (channels, rate) == (2, RATE)
    assert frames[0::2] == [100, -200, 30000, -30000, 5]
    assert frames[1::2] == [1, 2, 30000, -30000, 0]


@pytest.mark.parametrize("mixer_type", [MonoMixer, StereoMixer])
def test_mixing_streams_in_blocks(
    tmp_path: Path, mixer_type: type[MonoMixer] | type[StereoMixer]
) -> None:
    samples = list(range(250))
    reader = _reader(samples, [0] * 120)
    mixed = tmp_path / "mixed.wav"

    mixer_type(block_seconds=1).mix(reader, SESSION, mixed)

    channels, _, frames = _read(mixed)
    assert frames[0::channels] == samples
    assert [start for channel, start, _ in reader.reads if channel is Channel.MIC] == [0, 100, 200]


def test_system_track_longer_than_mic_is_kept(tmp_path: Path) -> None:
    MonoMixer().mix(_reader([1], [1, 2, 3]), SESSION, tmp_path / "mixed.wav")

    assert _read(tmp_path / "mixed.wav")[2] == [2, 2, 3]


def test_tracks_with_different_rates_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        MonoMixer().mix(_reader([1, 2], [1, 2], RATE * 2), SESSION, tmp_path / "mixed.wav")

    assert not (tmp_path / "mixed.wav").exists()


def test_empty_tracks_give_an_empty_mix(tmp_path: Path) -> None:
    MonoMixer().mix(_reader([], []), SESSION, tmp_path / "mixed.wav")

    assert _read(tmp_path / "mixed.wav") == (1, RATE, [])
