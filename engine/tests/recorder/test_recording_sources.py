"""`Recording` with every source (phase 65): raw tracks, the mix into the channels, selection."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.fakes import FakeAudioSource
from tests.recorder.test_recording import Observer, Time, settings, timeline
from vozata.audio.devices import DeviceInfo
from vozata.audio.opener import SourceOpenTimeoutError
from vozata.domain import Channel
from vozata.recorder.manifest import STOPPED, read_manifest, write_manifest
from vozata.recorder.recording import Recording, RecordingError, mark_stopped
from vozata.recorder.source_capture import FAILED, GONE, OPEN
from vozata.recorder.sources import SourceSpec, build_sources

RATE = 1000
JBL = DeviceInfo(20, "Microfone (JBL)", 1, 48000, False)
ROOM = DeviceInfo(21, "Microfone (Sala 2)", 1, 48000, False)
HEADSET = DeviceInfo(23, "Fones (JBL) [Loopback]", 2, 48000, True)
REALTEK = DeviceInfo(24, "Alto-falantes (Realtek) [Loopback]", 2, 48000, True)


class SourceObserver(Observer):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[list[dict[str, Any]]] = []

    def on_sources(self, sources: list[dict[str, Any]]) -> None:
        self.sources.append(sources)


class Devices:
    """Source factory: one `FakeAudioSource` per device id; some fail."""

    def __init__(self, fail: dict[int, Exception] | None = None) -> None:
        self.made: dict[int, FakeAudioSource] = {}
        self.fail = fail or {}

    def __call__(self, device: DeviceInfo, clock: Any) -> Any:
        source = _Failing(self.fail[device.id]) if device.id in self.fail else FakeAudioSource()
        self.made[device.id] = source
        return source


class _Failing(FakeAudioSource):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def start(self, on_samples: Any) -> None:
        raise self.error


def specs() -> list[SourceSpec]:
    return build_sources(
        [JBL, ROOM], [HEADSET, REALTEK], {Channel.MIC: JBL, Channel.SYSTEM: REALTEK}
    )


def speech(seconds: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = round(seconds * RATE)
    signal = rng.normal(0, 0.3, n).clip(-1, 1).astype(np.float32)
    return signal * (np.arange(n) // 200 % 2 == 0)


def create(tmp_path: Path, time: Time, devices: Devices, observer: Observer) -> Recording:
    chosen = specs()
    return Recording.create(
        tmp_path / "live",
        settings(tmp_path),
        {spec.kind: spec.device for spec in chosen if spec.preferred},
        devices,
        observer,
        wall_clock=time.now,
        time_source=time.mono,
        sources=chosen,
    )


def raw(recording: Recording, source_id: str) -> np.ndarray:
    with wave.open(str(recording.folder / "sources" / f"{source_id}.wav"), "rb") as file:
        data = np.frombuffer(file.readframes(file.getnframes()), np.int16)
    return data.astype(np.float32) / 32767


def mixed(recording: Recording, channel: Channel) -> np.ndarray:
    return timeline(recording, channel).astype(np.float32) / 32767


def wait_settled(recording: Recording) -> None:
    for _ in range(200):
        sources = recording.sources() or []
        if all(source["state"] != "pending" for source in sources):
            return
        import time as clock

        clock.sleep(0.01)
    raise AssertionError("the sources did not settle")


def wait_opened(devices: Devices, count: int) -> None:
    for _ in range(200):
        if sum(source.started for source in devices.made.values()) >= count:
            return
        import time as clock

        clock.sleep(0.01)
    raise AssertionError("the sources did not open")


def test_every_source_is_recorded_and_the_speaking_ones_are_mixed(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_opened(devices, 4)
    words, call = speech(4.0), speech(4.0, seed=2)
    devices.made[20].push(np.zeros(4000, np.float32), 0.0)  # the preferred mic: silent
    devices.made[21].push(words, 0.0)  # the mic of the other room speaks
    devices.made[23].push(call, 0.0)  # the call plays on the headset
    devices.made[24].push(np.zeros(4000, np.float32), 0.0)  # the preferred loopback: silent
    time.advance(4.0)

    recording.stop()

    manifest = read_manifest(recording.folder)
    assert manifest.status == STOPPED
    assert sorted(manifest.sources) == [
        "in-microfone-jbl",
        "in-microfone-sala-2",
        "out-alto-falantes-realtek",
        "out-fones-jbl",
    ]
    assert all(entry["state"] == OPEN for entry in manifest.sources.values())
    selected = {i for i, entry in manifest.sources.items() if entry["selected"]}
    assert selected == {"in-microfone-sala-2", "out-fones-jbl"}
    assert np.allclose(mixed(recording, Channel.MIC), words, atol=1e-3)
    assert np.allclose(mixed(recording, Channel.SYSTEM), call, atol=1e-3)
    assert np.allclose(raw(recording, "in-microfone-sala-2"), words, atol=1e-3)
    assert len(raw(recording, "in-microfone-jbl")) == 4000
    log = {(entry["source"], entry["selected"], entry["by"]) for entry in manifest.selection_log}
    assert ("in-microfone-sala-2", True, "auto") in log
    assert ("in-microfone-jbl", False, "auto") in log
    assert recording.summary()["capture"] == "all"
    assert ("all_sources_silent", "Every audio device gives only silence") not in observer.errors
    assert observer.sources[-1][0]["id"] == "in-microfone-jbl"


def test_a_source_switched_off_by_the_user_is_not_mixed(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_opened(devices, 4)

    recording.set_source_mode("in-microfone-sala-2", "off")
    devices.made[21].push(speech(2.0), 0.0)
    time.advance(2.0)
    recording.stop()

    manifest = read_manifest(recording.folder)
    assert manifest.sources["in-microfone-sala-2"]["mode"] == "off"
    assert not timeline(recording, Channel.MIC).any()
    with pytest.raises(KeyError):
        recording.set_source_mode("in-nope", "on")
    sources = recording.sources()
    assert sources is not None and {s["mode"] for s in sources} == {"auto", "off"}


def test_a_source_that_fails_is_skipped_and_reported(tmp_path: Path) -> None:
    time, observer = Time(), SourceObserver()
    devices = Devices(fail={21: OSError("device busy"), 23: SourceOpenTimeoutError("hung")})
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_settled(recording)
    recording.stop()

    manifest = read_manifest(recording.folder)
    states = {i: entry["state"] for i, entry in manifest.sources.items()}
    assert states["in-microfone-sala-2"] == FAILED
    assert states["out-fones-jbl"] == FAILED
    assert manifest.sources["in-microfone-sala-2"]["error"] == "Microfone (Sala 2): device busy"
    assert "did not open" in manifest.sources["out-fones-jbl"]["error"]
    assert [code for code, _ in observer.errors].count("source_failed") == 2


def test_the_others_open_when_every_preferred_source_fails(tmp_path: Path) -> None:
    time, observer = Time(), SourceObserver()
    devices = Devices(fail={20: OSError("x"), 24: OSError("y")})
    recording = create(tmp_path, time, devices, observer)

    recording.start()

    assert devices.made[21].started and devices.made[23].started
    recording.stop()


def test_start_fails_when_no_source_opens(tmp_path: Path) -> None:
    time, observer = Time(), SourceObserver()
    devices = Devices(fail={i: OSError("gone") for i in (20, 21, 23, 24)})
    recording = create(tmp_path, time, devices, observer)

    with pytest.raises(RecordingError) as error:
        recording.start()

    assert error.value.code == "device_failed"
    assert read_manifest(recording.folder).stop_reason == "device_failed"


def test_every_source_silent_is_reported_once(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_opened(devices, 4)
    for source in devices.made.values():
        source.push(np.zeros(3000, np.float32), 0.0)
    time.advance(3.0)
    for _ in range(10):
        recording._capture.step()  # type: ignore[union-attr]

    recording.stop()

    assert [code for code, _ in observer.errors].count("all_sources_silent") == 1


def test_pause_silences_the_sources_too(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_opened(devices, 4)
    recording.pause()
    devices.made[21].push(speech(1.0), 0.0)
    recording.resume_capture()
    recording.stop()

    assert not raw(recording, "in-microfone-sala-2").any()


def test_resume_continues_the_saved_sources_and_marks_the_missing_ones(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    first = create(tmp_path, time, devices, observer)
    first.start()
    wait_opened(devices, 4)
    devices.made[21].push(speech(2.0), 0.0)
    time.advance(2.0)
    first._capture.step()  # type: ignore[union-attr]
    first._capture.stop_sources()  # type: ignore[union-attr]  # the recorder "dies"
    for track in first._all_tracks():
        track.close()
    manifest = read_manifest(first.folder)
    manifest.sources["in-microfone-sala-2"]["segments"][-1].closed = False
    write_manifest(first.folder, manifest)
    time.advance(1.0)
    again = [spec for spec in specs() if spec.device.id != 24]  # the Realtek is unplugged

    resumed = Recording.resume(
        first.folder,
        settings(tmp_path),
        {Channel.MIC: JBL},
        Devices(),
        observer,
        wall_clock=time.now,
        time_source=time.mono,
        sources=again,
    )
    resumed.start()
    resumed.stop()

    manifest = read_manifest(first.folder)
    assert manifest.sources["out-alto-falantes-realtek"]["state"] == GONE
    assert manifest.sources["in-microfone-sala-2"]["segments"][0].frames == 2000
    gaps = {gap.channel: (gap.start_frame, gap.end_frame) for gap in manifest.gaps}
    assert gaps["in-microfone-sala-2"] == (2000, 3000)
    assert manifest.sources["in-microfone-sala-2"]["selected"]  # kept from before the crash


def test_mark_stopped_closes_the_open_source_segments(tmp_path: Path) -> None:
    time, devices, observer = Time(), Devices(), SourceObserver()
    recording = create(tmp_path, time, devices, observer)
    recording.start()
    wait_opened(devices, 4)
    devices.made[21].push(speech(1.0), 0.0)
    recording._capture.stop_sources()  # type: ignore[union-attr]
    for track in recording._all_tracks():
        track.close()
    manifest = read_manifest(recording.folder)
    manifest.status = "recording"
    manifest.sources["in-microfone-sala-2"]["segments"][-1].closed = False
    write_manifest(recording.folder, manifest)

    stopped = mark_stopped(recording.folder, "recorder_died", time.now())

    assert stopped.sources["in-microfone-sala-2"]["segments"][-1].closed
    assert stopped.sources["in-microfone-sala-2"]["segments"][-1].frames == 1000
