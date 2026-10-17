from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from vozata.storage.wav_repair import WavRepairError, pad_wav, repair_wav, wav_frames

RATE = 16000


def write_wav(path: Path, samples: np.ndarray, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.astype(np.int16).tobytes())


def read_samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)


def ramp(frames: int) -> np.ndarray:
    return (np.arange(frames) % 2000).astype(np.int16)


def set_sizes(path: Path, riff: int, data: int) -> None:
    with path.open("r+b") as file:
        file.seek(4)
        file.write(struct.pack("<I", riff))
        file.seek(40)
        file.write(struct.pack("<I", data))


def test_a_truncated_file_with_a_stale_header_is_repaired_and_readable(tmp_path: Path) -> None:
    path = tmp_path / "mic.wav"
    write_wav(path, ramp(RATE))
    with path.open("r+b") as file:  # the crash: the last 0.25 s never reached the disk
        file.truncate(44 + RATE // 2 * 3 + 1)  # ends in the middle of a frame

    frames = repair_wav(path, RATE)

    assert frames == RATE // 4 * 3
    assert wav_frames(path) == frames
    assert np.array_equal(read_samples(path), ramp(RATE)[:frames])


def test_a_header_that_still_says_empty_is_repaired(tmp_path: Path) -> None:
    path = tmp_path / "system.wav"
    write_wav(path, ramp(800))
    set_sizes(path, 36, 0)  # sizes as written before the first frames

    assert repair_wav(path, RATE) == 800
    assert np.array_equal(read_samples(path), ramp(800))


def test_repairing_a_valid_file_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "mic.wav"
    write_wav(path, ramp(500))
    before = path.read_bytes()

    assert repair_wav(path, RATE) == 500
    assert path.read_bytes() == before


def test_a_missing_or_empty_file_becomes_an_empty_wav(tmp_path: Path) -> None:
    missing = tmp_path / "mic.wav"
    empty = tmp_path / "system.wav"
    empty.write_bytes(b"")

    assert repair_wav(missing, RATE) == 0
    assert repair_wav(empty, RATE) == 0
    for path in (missing, empty):
        with wave.open(str(path), "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, RATE)
            assert wav.getnframes() == 0


def test_extra_chunks_before_the_data_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "mic.wav"
    write_wav(path, ramp(100))
    raw = path.read_bytes()
    extra = b"LIST" + struct.pack("<I", 3) + b"abc\x00"  # odd size: padded to even
    path.write_bytes(raw[:36] + extra + raw[36:])

    assert repair_wav(path, RATE) == 100
    assert np.array_equal(read_samples(path), ramp(100))


def test_stereo_frames_count_both_channels(tmp_path: Path) -> None:
    path = tmp_path / "mixed.wav"
    write_wav(path, ramp(200), channels=2)

    assert repair_wav(path, RATE) == 100


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"garbage that is not a wav file", "RIFF"),
        (b"RIFF\x00\x00\x00\x00WAVE", "data chunk"),
        (b"RIFF\x00\x00\x00\x00WAVEdata\x00\x00\x00\x00", "fmt"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt \x04\x00\x00\x00abcd", "truncated fmt"),
    ],
)
def test_an_unreadable_header_raises(tmp_path: Path, content: bytes, reason: str) -> None:
    path = tmp_path / "mic.wav"
    path.write_bytes(content)

    with pytest.raises(WavRepairError, match=reason):
        repair_wav(path, RATE)
    assert path.read_bytes() == content  # never changed


def test_compressed_audio_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mic.wav"
    write_wav(path, ramp(10))
    with path.open("r+b") as file:
        file.seek(20)
        file.write(struct.pack("<H", 3))  # IEEE float, not PCM

    with pytest.raises(WavRepairError, match="not PCM"):
        repair_wav(path, RATE)


def test_pad_appends_silence_up_to_the_frame_count(tmp_path: Path) -> None:
    path = tmp_path / "system.wav"
    write_wav(path, ramp(300))

    pad_wav(path, 1000)

    samples = read_samples(path)
    assert len(samples) == 1000
    assert np.array_equal(samples[:300], ramp(300))
    assert not samples[300:].any()


def test_pad_never_shortens(tmp_path: Path) -> None:
    path = tmp_path / "mic.wav"
    write_wav(path, ramp(300))
    before = path.read_bytes()

    pad_wav(path, 100)

    assert path.read_bytes() == before
