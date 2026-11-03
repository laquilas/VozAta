from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import pytest

from vozata.domain import Channel
from vozata.recorder.durable_track import DurableTrack, TrackWriteError
from vozata.recorder.manifest import (
    REASON_SIZE_LIMIT,
    REASON_START,
    REASON_WRITE_ERROR,
    Manifest,
    Segment,
)
from vozata.recorder.segment_reader import SegmentReader

RATE = 1000  # small numbers keep the arithmetic readable


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class FlakyFile:
    """A real file whose write / flush can be told to fail."""

    def __init__(self, file: BinaryIO, plan: Plan) -> None:
        self._file = file
        self._plan = plan

    def write(self, data: bytes) -> int:
        if self._plan.fail_write:
            self._plan.fail_write -= 1
            self._file.write(data[: len(data) // 2])  # a torn write
            raise OSError("disk full")
        return self._file.write(data)

    def flush(self) -> None:
        if self._plan.fail_flush:
            self._plan.fail_flush -= 1
            raise OSError("locked")
        self._file.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._file, name)


class Plan:
    def __init__(self) -> None:
        self.fail_write = 0
        self.fail_flush = 0
        self.fail_create = 0


class Rig:
    def __init__(self, folder: Path, **options: Any) -> None:
        self.folder = folder
        self.clock = Clock()
        self.plan = Plan()
        self.manifest = Manifest(id="x", started_at="2026-11-03T10:00:00-03:00", sample_rate=RATE)
        self.saves = 0
        options.setdefault("fsync_seconds", 2.0)
        self.track = DurableTrack(
            folder,
            Channel.MIC,
            RATE,
            self.manifest.segments(Channel.MIC),
            threading.RLock(),
            self._save,
            now=self.clock,
            create=self._create,
            **options,
        )

    def _save(self) -> None:
        self.saves += 1

    def _create(self, path: Path) -> BinaryIO:
        if self.plan.fail_create:
            self.plan.fail_create -= 1
            raise PermissionError("access denied")
        return FlakyFile(path.open("x+b"), self.plan)  # type: ignore[return-value]

    @property
    def segments(self) -> list[Segment]:
        return self.manifest.segments(Channel.MIC)

    def timeline(self) -> np.ndarray:
        reader = SegmentReader(self.folder, self.manifest)
        return reader.frames(Channel.MIC, 0, reader.length(Channel.MIC))

    def step(self, seconds: float = 0.0) -> None:
        self.clock.t += seconds
        self.track.flush_once()


def tone(start: int, count: int) -> np.ndarray:
    return ((np.arange(start, start + count) % 100) / 200).astype(np.float32)


def pcm(samples: np.ndarray) -> np.ndarray:
    return (np.clip(samples, -1, 1) * 32767).astype(np.int16)


def test_one_continuous_wav_holds_every_sample(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    for i in range(5):
        rig.track.write(tone(i * 100, 100), i * 0.1)
        rig.step(0.1)

    rig.track.close()

    assert [segment.file for segment in rig.segments] == ["mic.wav"]
    assert rig.segments[0] == Segment("mic.wav", 0, 500, closed=True, reason=REASON_START)
    with wave.open(str(tmp_path / "mic.wav"), "rb") as wav:
        assert (wav.getnframes(), wav.getframerate(), wav.getnchannels()) == (500, RATE, 1)
    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 500)))


def test_a_late_block_is_preceded_by_silence_and_a_paused_block_is_silence(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.track.write(tone(0, 100), 0.0)
    rig.track.write(tone(0, 100), 0.5)  # 400 frames late
    rig.track.paused = True
    rig.track.write(tone(0, 100), 0.6)

    rig.track.close()

    timeline = rig.timeline()
    assert len(timeline) == 700
    assert not timeline[100:500].any()
    assert timeline[500:600].any()
    assert not timeline[600:].any()


def test_a_small_drift_is_not_padded(tmp_path: Path) -> None:
    rig = Rig(tmp_path, tolerance=0.15)
    rig.track.write(tone(0, 100), 0.0)
    rig.track.write(tone(100, 100), 0.2)  # 100 frames late, under the 150-frame tolerance

    assert rig.track.samples_written == 200


def test_frames_become_durable_only_at_the_fsync_cadence(tmp_path: Path) -> None:
    rig = Rig(tmp_path, fsync_seconds=2.0)
    rig.track.write(tone(0, 300), 0.0)

    rig.step(0.5)
    assert rig.track.durable_frames == 0
    assert rig.segments[0].frames == 0

    rig.step(2.0)
    assert rig.track.durable_frames == 300
    assert rig.segments[0].frames == 300
    assert rig.track.pending_seconds == 0


def test_a_failed_write_moves_to_a_new_segment_without_losing_or_repeating_a_sample(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.track.write(tone(0, 200), 0.0)
    rig.step(2.0)  # 200 frames durable
    rig.track.write(tone(200, 200), 0.2)
    rig.step(0.1)  # in the file, not yet fsynced
    rig.plan.fail_write = 1
    rig.track.write(tone(400, 200), 0.4)
    rig.step(0.1)  # fails: segment 1 closed at frame 200

    assert rig.segments[0].closed and rig.segments[0].frames == 200
    assert rig.track.pending_seconds == pytest.approx(0.4)

    rig.step(1.0)  # after the retry delay: everything after frame 200 goes to segment 2
    rig.track.close()

    assert [(s.file, s.start_frame, s.frames, s.reason) for s in rig.segments] == [
        ("mic.wav", 0, 200, REASON_START),
        ("mic-0002.wav", 200, 400, REASON_WRITE_ERROR),
    ]
    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 600)))
    assert rig.track.write_errors == 1


def test_a_failed_fsync_is_handled_like_a_failed_write(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.track.write(tone(0, 300), 0.0)
    rig.plan.fail_flush = 1
    rig.step(2.0)

    assert rig.segments[0].closed and rig.segments[0].frames == 0

    rig.step(1.0)
    rig.track.close()

    assert [s.start_frame for s in rig.segments] == [0, 0]
    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 300)))


def test_the_size_guard_rolls_over_without_a_gap(tmp_path: Path) -> None:
    rig = Rig(tmp_path, max_segment_bytes=44 + 2 * 100)
    rig.track.write(tone(0, 250), 0.0)
    rig.step(0.1)

    rig.track.close()

    assert [(s.start_frame, s.frames, s.reason) for s in rig.segments] == [
        (0, 100, REASON_START),
        (100, 100, REASON_SIZE_LIMIT),
        (200, 50, REASON_SIZE_LIMIT),
    ]
    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 250)))


def test_a_file_that_cannot_be_created_is_tried_again_with_a_growing_delay(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    rig.plan.fail_create = 2
    rig.track.write(tone(0, 100), 0.0)

    rig.step()  # fails, retry in 0.5 s
    rig.step(0.4)  # too early: nothing tried
    assert rig.plan.fail_create == 1
    rig.step(0.1)  # fails, retry in 1 s
    rig.step(0.5)
    assert rig.segments == []
    rig.step(0.5)
    rig.track.close()

    assert [s.file for s in rig.segments] == ["mic.wav"]
    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 100)))


def test_an_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "mic.wav").write_bytes(b"someone else's audio")
    rig = Rig(tmp_path)
    rig.track.write(tone(0, 10), 0.0)

    rig.track.close()

    assert (tmp_path / "mic.wav").read_bytes() == b"someone else's audio"
    assert rig.segments[0].file == "mic-0002.wav"


def test_close_reports_audio_it_could_not_make_durable_and_keeps_it(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.plan.fail_create = 10**6
    rig.track.write(tone(0, 100), 0.0)

    with pytest.raises(TrackWriteError, match="not yet on disk"):
        rig.track.close(timeout=0.0)

    assert rig.track.pending_seconds == pytest.approx(0.1)


def test_pad_to_appends_silence_up_to_a_length(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.track.write(tone(0, 100), 0.0)
    rig.track.pad_to(300)
    rig.track.pad_to(200)  # never shortens

    rig.track.close()

    assert len(rig.timeline()) == 300


def test_a_track_continues_a_timeline_after_a_restart(tmp_path: Path) -> None:
    rig = Rig(tmp_path, start_frame=1000, first_reason="recorder_restart")
    rig.track.write(tone(0, 100), 1.5)

    rig.track.close()

    assert [(s.start_frame, s.reason) for s in rig.segments] == [(1000, "recorder_restart")]
    assert rig.segments[0].frames == 600  # 500 frames of silence, then the block


def test_the_writer_thread_writes_and_closes(tmp_path: Path) -> None:
    rig = Rig(tmp_path, fsync_seconds=0.0)
    rig.track._now = time.monotonic  # real time for the thread
    rig.track.start()
    rig.track.write(tone(0, 100), 0.0)

    rig.track.close(timeout=5.0)

    np.testing.assert_array_equal(rig.timeline(), pcm(tone(0, 100)))
    assert rig.saves >= 2
