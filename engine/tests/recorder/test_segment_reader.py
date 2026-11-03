from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from vozata.domain import Channel
from vozata.recorder.manifest import Manifest, Segment
from vozata.recorder.segment_reader import SegmentReader, segment_frames

RATE = 16000


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.astype(np.int16).tobytes())


def stale_header(path: Path) -> None:
    """Zero the RIFF and data sizes, as a crash before the next header patch leaves them."""
    with path.open("r+b") as file:
        file.seek(4)
        file.write(bytes(4))
        file.seek(40)
        file.write(bytes(4))


def ramp(start: int, count: int) -> np.ndarray:
    return (np.arange(start, start + count) % 30000).astype(np.int16)


def _manifest(*segments: Segment) -> Manifest:
    manifest = Manifest(id="x", started_at="2026-11-03T10:15:00-03:00", sample_rate=RATE)
    manifest.segments(Channel.MIC).extend(segments)
    return manifest


def test_one_continuous_segment_reads_as_written(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 5000))
    reader = SegmentReader(tmp_path, _manifest(Segment("mic.wav", 0, 0)))

    assert reader.length(Channel.MIC) == 5000
    np.testing.assert_array_equal(reader.frames(Channel.MIC, 100, 50), ramp(100, 50))


def test_the_open_segment_is_read_by_its_file_size_not_its_header(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 3000))
    stale_header(tmp_path / "mic.wav")
    reader = SegmentReader(tmp_path, _manifest(Segment("mic.wav", 0, 1000)))

    assert segment_frames(tmp_path / "mic.wav") == 3000
    assert reader.length(Channel.MIC) == 3000
    np.testing.assert_array_equal(reader.frames(Channel.MIC, 2990, 10), ramp(2990, 10))


def test_a_closed_segment_ends_at_its_recorded_frames(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 3000))
    reader = SegmentReader(tmp_path, _manifest(Segment("mic.wav", 0, 2000, closed=True)))

    assert reader.length(Channel.MIC) == 2000


def test_segments_join_and_gaps_read_as_silence(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 1000))
    write_wav(tmp_path / "mic-0002.wav", ramp(5000, 500))
    reader = SegmentReader(
        tmp_path,
        _manifest(Segment("mic.wav", 0, 1000, closed=True), Segment("mic-0002.wav", 1500, 0)),
    )

    samples = reader.frames(Channel.MIC, 990, 1020)

    assert reader.length(Channel.MIC) == 2000
    np.testing.assert_array_equal(samples[:10], ramp(990, 10))
    assert not samples[10:510].any()
    np.testing.assert_array_equal(samples[510:], ramp(5000, 500))


def test_reading_past_the_end_returns_what_there_is(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 100))
    reader = SegmentReader(tmp_path, _manifest(Segment("mic.wav", 0, 0)))

    assert len(reader.frames(Channel.MIC, 90, 50)) == 10
    assert len(reader.frames(Channel.MIC, 200, 50)) == 0


def test_a_missing_or_headerless_segment_holds_no_frames(tmp_path: Path) -> None:
    (tmp_path / "empty.wav").write_bytes(b"")
    reader = SegmentReader(tmp_path, _manifest(Segment("missing.wav", 0, 0)))

    assert segment_frames(tmp_path / "missing.wav") == 0
    assert segment_frames(tmp_path / "empty.wav") == 0
    assert reader.length(Channel.MIC) == 0
    assert reader.length(Channel.SYSTEM) == 0


def test_a_trailing_partial_frame_is_not_counted(tmp_path: Path) -> None:
    write_wav(tmp_path / "mic.wav", ramp(0, 10))
    with (tmp_path / "mic.wav").open("ab") as file:
        file.write(b"\x01")

    assert segment_frames(tmp_path / "mic.wav") == 10
