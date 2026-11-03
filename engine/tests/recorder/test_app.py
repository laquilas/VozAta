from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.audio.test_devices import FakePyAudio
from tests.fakes import FakeAudioSource
from vozata.audio.devices import DeviceInfo
from vozata.domain import Channel
from vozata.recorder.app import RESUME_WINDOW, RecorderApp
from vozata.recorder.http import RecorderServer
from vozata.recorder.manifest import STOPPED, live_dir, read_manifest, write_manifest
from vozata.recorder.recording import Recording
from vozata.recorder.segment_reader import SegmentReader
from vozata.recorder.settings import RecorderSettings

RATE = 1000
ZONE = timezone(timedelta(hours=-3))
MIC = DeviceInfo(2, "Headset mic", 1, 48000, False)
LOOPBACK = DeviceInfo(3, "Speakers [Loopback]", 2, 48000, True)


class FakeAudio:
    def __init__(self, fail: Exception | None = None) -> None:
        if fail is not None:
            raise fail
        self.pa = FakePyAudio()
        self.closed = False

    def call(self, function: Any, timeout: float | None = None) -> Any:
        return function()

    def close(self) -> None:
        self.closed = True


class Catalog:
    def inputs(self) -> list[DeviceInfo]:
        return [MIC]

    def loopbacks(self) -> list[DeviceInfo]:
        return [LOOPBACK]

    def default_input(self) -> DeviceInfo | None:
        return MIC

    def default_loopback(self) -> DeviceInfo | None:
        return None


class Sources:
    def __init__(self) -> None:
        self.made: dict[int, FakeAudioSource] = {}
        self.audios: list[FakeAudio] = []

    def __call__(self, audio: FakeAudio, rate: int) -> Any:
        self.audios.append(audio)

        def make(device: DeviceInfo, clock: Any) -> FakeAudioSource:
            source = FakeAudioSource()
            self.made[device.id] = source
            return source

        return make


class Wall:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 3, 10, 15, 0, tzinfo=ZONE)

    def __call__(self) -> datetime:
        return self.now


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = None if body is None else json.dumps(body)
        headers = {"Content-Type": "application/json"} if data else {}
        connection.request(method, path, body=data, headers=headers)
        reply = connection.getresponse()
        raw = reply.read()
        connection.close()
        return reply.status, json.loads(raw) if raw else None


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path)
    yield rig
    rig.close()


class Rig:
    def __init__(self, tmp_path: Path, audio_fail: Exception | None = None) -> None:
        self.tmp = tmp_path
        self.sources = Sources()
        self.wall = Wall()
        self.audio_fail = audio_fail
        self.settings = RecorderSettings(
            output_dir=tmp_path, sample_rate=RATE, autosave_seconds=60, fsync_seconds=0.5
        )
        self.app = RecorderApp(
            self.settings,
            Catalog(),
            lambda: FakeAudio(self.audio_fail),
            self.sources,
            self.wall,
            keep_alive=0.05,
        )
        self.server = RecorderServer(0, self.app.router)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.server.port)

    def close(self) -> None:
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def test_health_says_who_answers(rig: Rig) -> None:
    status, body = rig.client.request("GET", "/health")

    assert status == 200
    assert body["recorder"] == "ok"
    assert body["recording"] is None


def test_devices_have_the_engines_shape(rig: Rig) -> None:
    status, body = rig.client.request("GET", "/devices")

    assert status == 200
    assert body == {
        "inputs": [{"id": 2, "name": "Headset mic", "sample_rate": 48000, "channels": 1}],
        "loopbacks": [
            {"id": 3, "name": "Speakers [Loopback]", "sample_rate": 48000, "channels": 2}
        ],
        "default_input_id": 2,
        "default_loopback_id": None,
    }


def test_a_recording_starts_pauses_resumes_and_stops(rig: Rig) -> None:
    status, started = rig.client.request(
        "POST", "/recordings", {"mic_device_id": 2, "options": {"language": "pt"}}
    )
    assert status == 201
    assert started["status"] == "recording"
    assert started["id"] == "20261103_101500"
    assert started["options"] == {"language": "pt"}
    rig.sources.made[2].push(np.full(100, 0.3, dtype=np.float32), 0.0)

    assert rig.client.request("POST", "/recordings/current/pause")[1]["status"] == "paused"
    assert rig.client.request("POST", "/recordings/current/resume")[1]["status"] == "recording"
    _, patched = rig.client.request("PATCH", "/recordings/current", {"options": {"title": "A"}})
    assert patched["options"] == {"language": "pt", "title": "A"}
    assert rig.client.request("GET", "/recordings/current")[1]["id"] == started["id"]
    status, stopped = rig.client.request("POST", "/recordings/current/stop")

    assert (status, stopped["status"]) == (200, STOPPED)
    assert rig.sources.audios[0].closed
    folder = live_dir(rig.tmp) / started["id"]
    reader = SegmentReader(folder, read_manifest(folder))
    assert reader.length(Channel.MIC) == 100
    assert rig.client.request("GET", "/recordings/current")[0] == 404


def test_a_second_start_is_refused(rig: Rig) -> None:
    rig.client.request("POST", "/recordings", {})

    status, body = rig.client.request("POST", "/recordings", {})

    assert (status, body["error"]["code"]) == (409, "recording_already_active")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"mic_device_id": 99}, "device_not_found"),
        ({"mic_device_id": "2"}, "invalid_device"),
        ({"options": []}, "invalid_options"),
    ],
)
def test_bad_start_requests_are_refused(rig: Rig, body: dict[str, Any], code: str) -> None:
    status, reply = rig.client.request("POST", "/recordings", body)

    assert reply["error"]["code"] == code
    assert status in (404, 422)


def test_a_wedged_audio_backend_is_reported(tmp_path: Path) -> None:
    rig = Rig(tmp_path, audio_fail=TimeoutError("PortAudio did not answer"))
    try:
        status, body = rig.client.request("POST", "/recordings", {})
    finally:
        rig.close()

    assert (status, body["error"]["code"]) == (503, "audio_unavailable")


def test_controls_without_a_recording_say_so(rig: Rig) -> None:
    for method, path in [
        ("POST", "/recordings/current/pause"),
        ("POST", "/recordings/current/stop"),
        ("PATCH", "/recordings/current"),
    ]:
        status, body = rig.client.request(method, path, {"options": {}})
        assert (status, body["error"]["code"]) == (404, "no_active_recording")


def test_recordings_are_listed_read_and_deleted_once_stopped(rig: Rig) -> None:
    _, started = rig.client.request("POST", "/recordings", {})
    recording_id = started["id"]

    assert rig.client.request("DELETE", f"/recordings/{recording_id}")[0] == 409
    rig.client.request("POST", "/recordings/current/stop")
    _, listed = rig.client.request("GET", "/recordings")
    status, manifest = rig.client.request("GET", f"/recordings/{recording_id}")

    assert [item["id"] for item in listed["items"]] == [recording_id]
    assert (status, manifest["status"]) == (200, STOPPED)
    assert rig.client.request("DELETE", f"/recordings/{recording_id}")[0] == 204
    assert rig.client.request("GET", f"/recordings/{recording_id}")[0] == 404
    assert rig.client.request("GET", "/recordings/..")[0] == 404


def test_unknown_routes_methods_and_bodies(rig: Rig) -> None:
    assert rig.client.request("GET", "/nothing")[0] == 404
    assert rig.client.request("DELETE", "/health")[0] == 405
    connection = http.client.HTTPConnection("127.0.0.1", rig.server.port, timeout=5)
    connection.request("POST", "/recordings", body=b"{not json", headers={"Content-Length": "9"})
    assert connection.getresponse().status == 400
    connection.close()


def test_events_stream_the_status_and_levels(rig: Rig) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", rig.server.port, timeout=5)
    connection.request("GET", "/events")
    reply = connection.getresponse()
    assert reply.getheader("Content-Type", "").startswith("text/event-stream")

    def next_event() -> tuple[str, Any]:
        event = None
        while True:
            line = reply.fp.readline().decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                return event, json.loads(line[6:])

    assert next_event() == ("status", {"id": None, "status": "idle", "duration_seconds": 0})
    rig.client.request("POST", "/recordings", {})
    assert next_event()[1]["status"] == "recording"
    rig.sources.made[2].push(np.full(10, 0.5, dtype=np.float32), 0.0)
    event, data = next_event()
    while event != "level":
        event, data = next_event()
    assert data["channel"] == "mic" and data["rms_db"] == pytest.approx(-6.0, abs=0.1)
    rig.client.request("POST", "/recordings/current/stop")
    connection.close()


def test_shutdown_waits_for_the_recording_to_stop(rig: Rig) -> None:
    rig.client.request("POST", "/recordings", {})

    assert rig.client.request("POST", "/shutdown")[0] == 409
    rig.client.request("POST", "/recordings/current/stop")
    assert rig.client.request("POST", "/shutdown")[0] == 202
    assert rig.app.shutdown_requested.is_set()


def test_closing_the_app_stops_the_recording_cleanly(rig: Rig) -> None:
    _, started = rig.client.request("POST", "/recordings", {})

    rig.app.close()

    manifest = read_manifest(live_dir(rig.tmp) / started["id"])
    assert (manifest.status, manifest.stop_reason) == (STOPPED, "recorder_closed")


def _left_running(rig: Rig, heartbeat_age: float) -> str:
    """A recording whose recorder died `heartbeat_age` seconds ago."""
    recording = Recording.create(
        live_dir(rig.tmp),
        rig.settings,
        {Channel.MIC: MIC, Channel.SYSTEM: LOOPBACK},
        lambda device, clock: FakeAudioSource(),
        rig.app,
        wall_clock=rig.wall,
    )
    recording.start()
    recording.manifest.last_heartbeat_at = rig.wall().isoformat(timespec="seconds")
    recording.save()
    for track in recording._tracks.values():
        track._closed.set()  # its threads died with the process
    rig.wall.now += timedelta(seconds=heartbeat_age)
    return recording.id


def test_start_up_continues_a_recording_left_by_a_recorder_that_just_died(rig: Rig) -> None:
    recording_id = _left_running(rig, 5)

    rig.app.start_up()

    current = rig.app.current
    assert current is not None and current.id == recording_id
    assert read_manifest(live_dir(rig.tmp) / recording_id).incarnation == 2
    rig.client.request("POST", "/recordings/current/stop")


def test_start_up_closes_a_recording_left_long_ago(rig: Rig) -> None:
    recording_id = _left_running(rig, RESUME_WINDOW + 1)

    rig.app.start_up()

    manifest = read_manifest(live_dir(rig.tmp) / recording_id)
    assert rig.app.current is None
    assert (manifest.status, manifest.stop_reason) == (STOPPED, "recorder_died")


def test_a_recording_is_continued_through_the_api(rig: Rig) -> None:
    recording_id = _left_running(rig, RESUME_WINDOW + 1)

    status, summary = rig.client.request("POST", f"/recordings/{recording_id}/resume")

    assert (status, summary["incarnation"]) == (200, 2)
    rig.client.request("POST", "/recordings/current/stop")
    status, body = rig.client.request("POST", f"/recordings/{recording_id}/resume")
    assert (status, body["error"]["code"]) == (409, "recording_stopped")


def test_an_unreadable_manifest_is_skipped_at_start_up(rig: Rig) -> None:
    folder = live_dir(rig.tmp) / "20261101_090000"
    folder.mkdir(parents=True)
    (folder / "recording.json").write_text("{broken", encoding="utf-8")

    rig.app.start_up()

    assert rig.app.current is None
    assert rig.client.request("GET", "/recordings")[1] == {"items": []}


def test_a_listed_stopped_recording_shows_its_stop_reason(rig: Rig) -> None:
    recording_id = _left_running(rig, RESUME_WINDOW + 1)
    rig.app.start_up()

    _, listed = rig.client.request("GET", "/recordings")

    assert listed["items"][0]["stop_reason"] == "recorder_died"
    manifest = read_manifest(live_dir(rig.tmp) / recording_id)
    write_manifest(live_dir(rig.tmp) / recording_id, manifest)
