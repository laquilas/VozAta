"""`PyAvDecoder` (phase 60): any audio file to mono 16-bit PCM at the engine's rate."""

from __future__ import annotations

import wave
from pathlib import Path

import av
import numpy as np
import pytest

from vozata.audio.decode import PyAvDecoder
from vozata.ports import AudioDecodeError, AudioDecoder

RATE = 16000


def _wav(path: Path, seconds: float, rate: int, channels: int) -> Path:
    frames = round(seconds * rate)
    tone = (np.sin(np.arange(frames) * 2 * np.pi * 440 / rate) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.repeat(tone, channels).tobytes())
    return path


def _flac(path: Path, seconds: float, rate: int) -> Path:
    """A compressed file written with PyAV itself."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream("flac", rate=rate, layout="stereo")
        frames = round(seconds * rate)
        samples = np.zeros((1, 2 * frames), dtype=np.int16)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="stereo")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def _samples(decoder: PyAvDecoder, path: Path) -> np.ndarray:
    return np.frombuffer(b"".join(decoder.blocks(path)), dtype="<i2")


def test_it_is_an_audio_decoder() -> None:
    assert isinstance(PyAvDecoder(RATE), AudioDecoder)


def test_a_mono_wav_at_the_engine_rate_keeps_every_sample(tmp_path: Path) -> None:
    path = _wav(tmp_path / "a.wav", 1.5, RATE, 1)

    samples = _samples(PyAvDecoder(RATE), path)

    assert len(samples) == round(1.5 * RATE)
    assert np.abs(samples).max() > 7000  # the tone, not silence


def test_a_stereo_44k_wav_becomes_mono_16k_of_the_same_length(tmp_path: Path) -> None:
    path = _wav(tmp_path / "a.wav", 2.0, 44100, 2)

    samples = _samples(PyAvDecoder(RATE), path)

    assert abs(len(samples) - 2 * RATE) <= RATE // 100  # within 10 ms of resampler delay


def test_a_compressed_file_is_decoded(tmp_path: Path) -> None:
    path = _flac(tmp_path / "a.flac", 1.0, 48000)

    samples = _samples(PyAvDecoder(RATE), path)

    assert abs(len(samples) - RATE) <= RATE // 100


def test_blocks_are_streamed_not_read_at_once(tmp_path: Path) -> None:
    path = _wav(tmp_path / "a.wav", 3.0, RATE, 1)

    blocks = list(PyAvDecoder(RATE).blocks(path))

    assert len(blocks) > 1
    assert all(len(block) % 2 == 0 for block in blocks)


def test_a_file_that_is_not_audio_raises(tmp_path: Path) -> None:
    path = tmp_path / "notes.mp3"
    path.write_text("not audio at all", encoding="utf-8")

    with pytest.raises(AudioDecodeError):
        list(PyAvDecoder(RATE).blocks(path))


def test_a_file_without_an_audio_stream_raises(tmp_path: Path) -> None:
    path = tmp_path / "video.mkv"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=1)
        stream.width = stream.height = 16
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame(16, 16, "yuv420p")
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)

    with pytest.raises(AudioDecodeError):
        list(PyAvDecoder(RATE).blocks(path))


def test_an_empty_wav_yields_nothing(tmp_path: Path) -> None:
    path = _wav(tmp_path / "a.wav", 0, RATE, 1)

    assert _samples(PyAvDecoder(RATE), path).size == 0


def test_the_duration_is_what_the_file_announces(tmp_path: Path) -> None:
    path = _wav(tmp_path / "a.wav", 2.5, 44100, 2)

    assert PyAvDecoder(RATE).duration(path) == pytest.approx(2.5, abs=0.01)


def test_the_duration_of_a_file_that_is_not_audio_is_unknown(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    assert PyAvDecoder(RATE).duration(path) is None
