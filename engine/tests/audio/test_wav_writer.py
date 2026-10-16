from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from vozata.audio.wav_writer import AlignedWavWriter
from vozata.ports import AudioSink

RATE = 100  # small rate keeps sample arithmetic readable


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, RATE)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)


def _ones(n: int, value: float = 0.5) -> np.ndarray:
    return np.full(n, value, dtype=np.float32)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "mic.wav"


def test_satisfies_the_audio_sink_port(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)
    writer.finalize(0)

    assert isinstance(writer, AudioSink)


def test_contiguous_blocks_are_written_back_to_back(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(_ones(10), at=0.0)
    writer.write(_ones(10), at=0.1)
    writer.finalize(0.2)

    assert len(_read(path)) == 20
    assert writer.samples_written == 20


def test_gap_beyond_tolerance_is_filled_with_silence(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE, tolerance=0.15)

    writer.write(_ones(10), at=0.0)
    writer.write(_ones(10), at=1.0)  # 0.9 s of loopback silence
    writer.finalize(1.1)

    data = _read(path)
    assert len(data) == 110
    assert not data[10:100].any()
    assert data[100:].all()


def test_small_jitter_within_tolerance_is_not_filled(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE, tolerance=0.15)

    writer.write(_ones(10), at=0.0)
    writer.write(_ones(10), at=0.2)  # 0.1 s late: within tolerance

    assert writer.samples_written == 20


def test_first_block_arriving_late_is_aligned_to_the_session_clock(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(_ones(10), at=0.5)

    assert writer.samples_written == 60


def test_block_overlapping_already_written_audio_is_appended(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(_ones(10), at=0.0)
    writer.write(_ones(10), at=0.05)

    assert writer.samples_written == 20


def test_paused_writer_writes_silence_of_the_same_length(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.paused = True
    writer.write(_ones(10), at=0.0)
    writer.paused = False
    writer.write(_ones(10), at=0.1)
    writer.finalize(0.2)

    data = _read(path)
    assert not data[:10].any()
    assert data[10:].all()


def test_finalize_pads_to_the_total_length(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(_ones(10), at=0.0)
    writer.finalize(2.0)

    assert len(_read(path)) == 200


def test_finalize_never_truncates(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(_ones(30), at=0.0)
    writer.finalize(0.1)

    assert len(_read(path)) == 30


def test_samples_are_converted_to_16_bit_with_clipping(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)

    writer.write(np.array([0.0, 0.5, 1.0, 2.0, -2.0], dtype=np.float32), at=0.0)
    writer.finalize(0)

    assert _read(path).tolist() == [0, 16383, 32767, 32767, -32767]


def test_finalize_twice_is_harmless_and_write_after_finalize_fails(path: Path) -> None:
    writer = AlignedWavWriter(path, RATE)
    writer.finalize(0.1)
    writer.finalize(0.5)

    assert len(_read(path)) == 10
    with pytest.raises(RuntimeError):
        writer.write(_ones(1), at=0.2)
