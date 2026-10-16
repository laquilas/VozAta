from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.ports import AudioMixer

RATE = 100


def _write(path: Path, samples: list[int], rate: int = RATE, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.array(samples, dtype=np.int16).tobytes())
    return path


def _read(path: Path) -> tuple[int, int, list[int]]:
    with wave.open(str(path), "rb") as wav:
        frames = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        return wav.getnchannels(), wav.getframerate(), frames.tolist()


@pytest.fixture
def tracks(tmp_path: Path) -> tuple[Path, Path, Path]:
    mic = _write(tmp_path / "mic.wav", [100, -200, 30000, -30000, 5])
    system = _write(tmp_path / "system.wav", [1, 2, 30000, -30000])
    return mic, system, tmp_path / "mixed.wav"


@pytest.mark.parametrize("mixer", [MonoMixer(), StereoMixer()])
def test_mixers_satisfy_the_port(mixer: object) -> None:
    assert isinstance(mixer, AudioMixer)


def test_mono_mix_sums_samples_and_clips(tracks: tuple[Path, Path, Path]) -> None:
    mic, system, mixed = tracks

    MonoMixer().mix(mic, system, mixed)

    assert _read(mixed) == (1, RATE, [101, -198, 32767, -32767, 5])


def test_stereo_mix_puts_mic_left_and_system_right(tracks: tuple[Path, Path, Path]) -> None:
    mic, system, mixed = tracks

    StereoMixer().mix(mic, system, mixed)

    channels, rate, frames = _read(mixed)
    assert (channels, rate) == (2, RATE)
    assert frames[0::2] == [100, -200, 30000, -30000, 5]
    assert frames[1::2] == [1, 2, 30000, -30000, 0]


@pytest.mark.parametrize("mixer_type", [MonoMixer, StereoMixer])
def test_mixing_streams_in_blocks(
    tmp_path: Path, mixer_type: type[MonoMixer] | type[StereoMixer]
) -> None:
    samples = list(range(250))
    mic = _write(tmp_path / "mic.wav", samples)
    system = _write(tmp_path / "system.wav", [0] * 120)
    mixed = tmp_path / "mixed.wav"

    mixer_type(block_seconds=1).mix(mic, system, mixed)

    channels, _, frames = _read(mixed)
    assert frames[0::channels] == samples


def test_system_track_longer_than_mic_is_kept(tmp_path: Path) -> None:
    mic = _write(tmp_path / "mic.wav", [1])
    system = _write(tmp_path / "system.wav", [1, 2, 3])

    MonoMixer().mix(mic, system, tmp_path / "mixed.wav")

    assert _read(tmp_path / "mixed.wav")[2] == [2, 2, 3]


@pytest.mark.parametrize(
    ("rate", "channels"),
    [(RATE * 2, 1), (RATE, 2)],
)
def test_incompatible_tracks_are_rejected(tmp_path: Path, rate: int, channels: int) -> None:
    mic = _write(tmp_path / "mic.wav", [1, 2])
    system = _write(tmp_path / "system.wav", [1, 2], rate=rate, channels=channels)

    with pytest.raises(ValueError):
        MonoMixer().mix(mic, system, tmp_path / "mixed.wav")
