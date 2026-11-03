from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.fakes import FakeAudioSource
from vozata.audio.devices import DeviceInfo
from vozata.domain import Channel
from vozata.recorder.manifest import (
    PAUSED,
    REASON_RESTART,
    RECORDING,
    STOPPED,
    Gap,
    read_manifest,
    write_manifest,
)
from vozata.recorder.recording import (
    OffsetClock,
    Recording,
    RecordingError,
    new_recording_id,
)
from vozata.recorder.segment_reader import SegmentReader
from vozata.recorder.settings import RecorderSettings

RATE = 1000
ZONE = timezone(timedelta(hours=-3))
DEVICES = {
    Channel.MIC: DeviceInfo(15, "Microfone (JBL)", 1, 48000, False),
    Channel.SYSTEM: DeviceInfo(16, "Alto-falantes (JBL) [Loopback]", 2, 48000, True),
}


class Observer:
    def __init__(self) -> None:
        self.statuses: list[dict[str, Any]] = []
        self.levels: list[tuple[Channel, float]] = []
        self.errors: list[tuple[str, str]] = []

    def on_status(self, summary: dict[str, Any]) -> None:
        self.statuses.append(summary)

    def on_level(self, channel: Channel, rms_db: float) -> None:
        self.levels.append((channel, rms_db))

    def on_error(self, code: str, message: str) -> None:
        self.errors.append((code, message))


class Time:
    def __init__(self) -> None:
        self.t = 100.0
        self.wall = datetime(2026, 11, 3, 10, 15, 0, tzinfo=ZONE)

    def mono(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.t += seconds
        self.wall += timedelta(seconds=seconds)


class Sources:
    def __init__(self, fail: dict[Channel, Exception] | None = None) -> None:
        self.made: dict[str, FakeAudioSource] = {}
        self.fail = fail or {}

    def __call__(self, device: DeviceInfo, clock: Any) -> Any:
        channel = Channel.MIC if device.id == 15 else Channel.SYSTEM
        source = _Failing(self.fail[channel]) if channel in self.fail else FakeAudioSource()
        self.made[channel.value] = source  # type: ignore[assignment]
        return source


class _Failing(FakeAudioSource):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def start(self, on_samples: Any) -> None:
        raise self.error


def settings(tmp_path: Path) -> RecorderSettings:
    return RecorderSettings(
        output_dir=tmp_path, sample_rate=RATE, autosave_seconds=60, fsync_seconds=0.5
    )


def block(count: int, value: float = 0.25) -> np.ndarray:
    return np.full(count, value, dtype=np.float32)


def create(tmp_path: Path, time: Time, sources: Sources, observer: Observer) -> Recording:
    return Recording.create(
        tmp_path / "live",
        settings(tmp_path),
        DEVICES,
        sources,
        observer,
        options={"language": "pt"},
        wall_clock=time.now,
        time_source=time.mono,
    )


def timeline(recording: Recording, channel: Channel) -> np.ndarray:
    manifest = read_manifest(recording.folder)
    reader = SegmentReader(recording.folder, manifest)
    return reader.frames(channel, 0, reader.length(channel))


def test_a_recording_writes_both_channels_and_a_manifest(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)

    recording.start()
    sources.made["mic"].push(block(500), 0.0)
    sources.made["system"].push(block(300, 0.5), 0.0)
    time.advance(0.5)
    recording.stop()

    manifest = read_manifest(recording.folder)
    assert recording.id == "20261103_101500"
    assert manifest.status == STOPPED
    assert manifest.started_at == "2026-11-03T10:15:00-03:00"
    assert manifest.devices["mic"] == {"id": 15, "name": "Microfone (JBL)"}
    assert manifest.options == {"language": "pt"}
    assert manifest.duration_seconds == 0.5
    assert len(timeline(recording, Channel.MIC)) == len(timeline(recording, Channel.SYSTEM)) == 500
    assert [s.file for s in manifest.segments(Channel.SYSTEM)] == ["system.wav"]
    assert {channel for channel, _ in observer.levels} == {Channel.MIC, Channel.SYSTEM}
    assert [status["status"] for status in observer.statuses] == [RECORDING, STOPPED]


def test_pause_writes_silence_and_records_the_pause(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()
    sources.made["mic"].push(block(100), 0.0)

    time.advance(0.1)
    recording.pause()
    sources.made["mic"].push(block(100), 0.1)
    time.advance(0.1)
    recording.resume_capture()
    sources.made["mic"].push(block(100), 0.2)
    recording.stop()

    mic = timeline(recording, Channel.MIC)
    assert mic[:100].all() and not mic[100:200].any() and mic[200:300].all()
    assert read_manifest(recording.folder).pauses == [{"start": 0.1, "end": 0.2}]
    assert [s["status"] for s in observer.statuses] == [RECORDING, PAUSED, RECORDING, STOPPED]


def test_a_paused_recording_stopped_closes_its_pause(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()
    recording.pause()
    time.advance(1.0)

    recording.stop()

    assert read_manifest(recording.folder).pauses == [{"start": 0.0, "end": 1.0}]


def test_pause_and_resume_out_of_order_do_nothing(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()

    recording.resume_capture()
    recording.pause()
    recording.pause()
    recording.stop()
    recording.stop()

    assert len(read_manifest(recording.folder).pauses) == 1


def test_options_are_merged_into_the_manifest(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()

    recording.update_options({"title": "Weekly"})

    assert read_manifest(recording.folder).options == {"language": "pt", "title": "Weekly"}
    assert recording.summary()["options"]["title"] == "Weekly"
    recording.stop()


def test_a_device_that_fails_stops_the_recording_and_is_reported(tmp_path: Path) -> None:
    time, observer = Time(), Observer()
    sources = Sources(fail={Channel.SYSTEM: OSError("Unanticipated host error")})
    recording = create(tmp_path, time, sources, observer)

    with pytest.raises(RecordingError) as error:
        recording.start()

    assert error.value.code == "device_failed"
    assert sources.made["mic"].stopped
    manifest = read_manifest(recording.folder)
    assert (manifest.status, manifest.stop_reason) == (STOPPED, "device_failed")


def test_the_ids_of_recordings_started_in_the_same_second_differ(tmp_path: Path) -> None:
    taken = {"20261103_101500", "20261103_101500_2"}
    start = datetime(2026, 11, 3, 10, 15, 0)

    assert new_recording_id(start, taken.__contains__) == "20261103_101500_3"


def test_a_dead_recorders_recording_continues_after_a_gap(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    first = create(tmp_path, time, sources, observer)
    first.start()
    sources.made["mic"].push(block(1000), 0.0)
    sources.made["system"].push(block(1000), 0.0)
    for track in first._tracks.values():  # the writer thread wrote it, then the process died
        track.flush_once()
    folder = first.folder
    time.advance(3.0)

    sources2 = Sources()
    second = Recording.resume(
        folder, settings(tmp_path), DEVICES, sources2, observer, time.now, time.mono
    )
    second.start()
    sources2.made["mic"].push(block(500, 0.5), 3.0)
    sources2.made["system"].push(block(500, 0.5), 3.0)
    second.stop()
    first._accepting = False  # the dead recorder's threads are gone in real life
    for track in first._tracks.values():
        track._closed.set()

    manifest = read_manifest(folder)
    mic = timeline(second, Channel.MIC)
    assert manifest.incarnation == 2
    assert [(s.start_frame, s.reason, s.closed) for s in manifest.segments(Channel.MIC)] == [
        (0, "start", True),
        (3000, REASON_RESTART, True),
    ]
    assert Gap("mic", 1000, 3000) in manifest.gaps
    assert len(mic) == 3500
    assert mic[:1000].all() and not mic[1000:3000].any() and mic[3000:].all()


def test_a_stopped_recording_cannot_be_resumed(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()
    recording.stop()

    with pytest.raises(RecordingError) as error:
        Recording.resume(recording.folder, settings(tmp_path), DEVICES, Sources(), observer)

    assert error.value.code == "recording_stopped"


def test_a_paused_recording_resumes_paused(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    first = create(tmp_path, time, sources, observer)
    first.start()
    first.pause()
    for track in first._tracks.values():
        track._closed.set()

    second = Recording.resume(
        first.folder, settings(tmp_path), DEVICES, Sources(), observer, time.now, time.mono
    )

    assert second.status == PAUSED
    assert all(track.paused for track in second._tracks.values())


def test_a_failing_manifest_save_is_reported_once_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.recorder import recording as module

    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()

    def locked(folder: Path, manifest: Any) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(module, "write_manifest", locked)
    recording.update_options({"a": 1})
    recording.update_options({"b": 2})
    monkeypatch.setattr(module, "write_manifest", write_manifest)
    recording.stop()

    assert [code for code, _ in observer.errors] == ["manifest_write_failed"]
    assert read_manifest(recording.folder).options["b"] == 2


def test_the_heartbeat_saves_the_duration_and_warns_about_a_disk_backlog(tmp_path: Path) -> None:
    time, sources, observer = Time(), Sources(), Observer()
    recording = create(tmp_path, time, sources, observer)
    recording.start()
    time.advance(2.0)
    recording._settings = RecorderSettings(sample_rate=RATE, buffer_warn_seconds=5)
    recording._tracks[Channel.MIC].write(block(10_000), 2.0)  # 10 s waiting in memory

    recording._beat()
    recording._beat()

    manifest = read_manifest(recording.folder)
    assert manifest.duration_seconds == 2.0
    assert manifest.last_heartbeat_at == "2026-11-03T10:15:02-03:00"
    assert [code for code, _ in observer.errors] == ["disk_backlog"]
    recording.stop()


def test_the_offset_clock_counts_from_its_offset() -> None:
    now = [10.0]
    clock = OffsetClock(5.0, lambda: now[0])

    assert clock.now() == 5.0
    clock.start()
    now[0] = 12.5
    assert clock.now() == 7.5
