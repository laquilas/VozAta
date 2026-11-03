from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from vozata.audio.recorder_clock import RecorderClock
from vozata.audio.tail_source import TailingFileSource
from vozata.domain import Channel
from vozata.recorder.durable_track import DurableTrack
from vozata.recorder.manifest import STOPPED, Manifest, read_manifest, write_manifest

RATE = 1000


class Live:
    """A recording being written by a `DurableTrack`, as the recorder process does."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.manifest = Manifest(id="x", started_at="2026-11-03T10:00:00-03:00", sample_rate=RATE)
        self.lock = threading.RLock()
        self.track = DurableTrack(
            folder,
            Channel.MIC,
            RATE,
            self.manifest.segments(Channel.MIC),
            self.lock,
            self.save,
            fsync_seconds=0.0,
            max_segment_bytes=44 + 2 * 700,
        )
        self.save()

    def save(self) -> None:
        with self.lock:
            write_manifest(self.folder, self.manifest)

    def write(self, start: int, count: int) -> None:
        self.track.write(ramp(start, count), start / RATE)
        self.track.flush_once()

    def stop(self) -> None:
        self.track.close()
        self.manifest.status = STOPPED
        self.save()


def ramp(start: int, count: int) -> np.ndarray:
    return ((np.arange(start, start + count) % 50) / 100).astype(np.float32)


class Collector:
    def __init__(self) -> None:
        self.blocks: list[tuple[np.ndarray, float]] = []

    def __call__(self, samples: np.ndarray, at: float) -> None:
        self.blocks.append((samples, at))

    @property
    def frames(self) -> int:
        return sum(len(samples) for samples, _ in self.blocks)

    def joined(self) -> np.ndarray:
        return np.concatenate([samples for samples, _ in self.blocks])


def wait_for(condition: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_the_backlog_is_replayed_then_the_recording_is_followed_to_its_end(
    tmp_path: Path,
) -> None:
    live = Live(tmp_path)
    live.write(0, 1000)  # recorded before the engine attached
    collector = Collector()
    source = TailingFileSource(tmp_path, Channel.MIC, RATE, poll=0.01, block_seconds=0.3)

    source.start(collector)
    wait_for(lambda: collector.frames == 1000)
    live.write(1000, 500)  # crosses into a second segment (the size guard)
    wait_for(lambda: collector.frames == 1500)
    live.stop()
    source.stop()

    assert source.finished.is_set()
    assert [at for _, at in collector.blocks][:2] == [0.0, 0.3]
    expected = (np.clip(ramp(0, 1500), -1, 1) * 32767).astype(np.int16) / 32767.0
    np.testing.assert_allclose(collector.joined(), expected, atol=1e-6)
    assert len(read_manifest(tmp_path).segments(Channel.MIC)) == 3


def test_stop_drains_a_stopped_recording(tmp_path: Path) -> None:
    live = Live(tmp_path)
    live.write(0, 600)
    live.stop()
    collector = Collector()
    source = TailingFileSource(tmp_path, Channel.MIC, RATE, poll=0.01, block_seconds=0.1)

    source.start(collector)
    source.stop()

    assert collector.frames == 600
    assert source.finished.is_set()


def test_stop_returns_at_once_while_the_recording_goes_on(tmp_path: Path) -> None:
    live = Live(tmp_path)
    live.write(0, 100)
    source = TailingFileSource(tmp_path, Channel.MIC, RATE, poll=0.01)
    source.start(Collector())

    began = time.monotonic()
    source.stop()

    assert time.monotonic() - began < 1.0
    assert not source.finished.is_set()
    live.stop()


def test_a_source_can_start_from_a_frame(tmp_path: Path) -> None:
    live = Live(tmp_path)
    live.write(0, 500)
    live.stop()
    collector = Collector()
    source = TailingFileSource(tmp_path, Channel.MIC, RATE, start_frame=400, poll=0.01)

    source.start(collector)
    source.stop()

    assert collector.frames == 100
    assert collector.blocks[0][1] == 0.4


def test_a_manifest_being_replaced_keeps_the_last_one(tmp_path: Path) -> None:
    live = Live(tmp_path)
    live.write(0, 200)
    live.stop()
    reads = [0]

    def flaky(folder: Path) -> Manifest:
        reads[0] += 1
        if reads[0] == 2:
            raise PermissionError("being replaced")
        return read_manifest(folder)

    collector = Collector()
    source = TailingFileSource(tmp_path, Channel.MIC, RATE, poll=0.01, read=flaky)
    source.start(collector)
    source.stop()

    assert collector.frames == 200


def test_stop_before_start_does_nothing(tmp_path: Path) -> None:
    TailingFileSource(tmp_path, Channel.MIC, RATE).stop()


def test_the_recorder_clock_counts_from_the_recording_start_and_freezes_at_stop() -> None:
    zone = timezone(timedelta(hours=-3))
    started = datetime(2026, 11, 3, 10, 0, 0, tzinfo=zone)
    now = [started + timedelta(seconds=12.5)]
    clock = RecorderClock(started, lambda: now[0])

    clock.start()
    assert clock.now() == 12.5
    clock.stop_at(13.0)
    now[0] += timedelta(seconds=30)
    assert clock.now() == 13.0
    assert RecorderClock(started, lambda: started - timedelta(seconds=1)).now() == 0.0
