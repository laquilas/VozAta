"""The recorder API with every source recorded (phase 65)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.audio.test_devices import FakePyAudio
from tests.fakes import FakeAudioSource
from tests.recorder.test_app import Rig
from vozata.recorder.manifest import live_dir, read_manifest
from vozata.recorder.recording import Recording
from vozata.recorder.sources import resolve_sources


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path, capture="all")
    yield rig
    rig.close()


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["items"]]


def test_a_recording_records_every_source(rig: Rig) -> None:
    status, summary = rig.client.request("POST", "/recordings", {})

    assert status == 201
    assert summary["capture"] == "all"
    assert summary["devices"]["mic"]["name"] == "Headset mic"  # the preferred one
    status, body = rig.client.request("GET", "/recordings/current/sources")
    assert status == 200
    assert _ids(body) == ["in-headset-mic", "in-usb-mic", "out-speakers"]
    assert {item["state"] for item in body["items"]} <= {"open", "pending"}
    rig.client.request("POST", "/recordings/current/stop")
    manifest = read_manifest(live_dir(rig.tmp) / summary["id"])
    assert sorted(manifest.sources) == ["in-headset-mic", "in-usb-mic", "out-speakers"]


def test_the_chosen_device_is_the_preferred_source(rig: Rig) -> None:
    rig.client.request("POST", "/recordings", {"mic_device_id": 4})

    _, body = rig.client.request("GET", "/recordings/current/sources")

    preferred = [item["id"] for item in body["items"] if item["preferred"]]
    assert preferred == ["in-usb-mic", "out-speakers"]
    rig.client.request("POST", "/recordings/current/stop")


def test_a_source_mode_is_set_through_the_api(rig: Rig) -> None:
    rig.client.request("POST", "/recordings", {})

    status, body = rig.client.request(
        "PUT", "/recordings/current/sources/in-usb-mic", {"mode": "on"}
    )

    assert status == 200
    usb = next(item for item in body["items"] if item["id"] == "in-usb-mic")
    assert (usb["mode"], usb["selected"]) == ("on", True)
    status, error = rig.client.request("PUT", "/recordings/current/sources/in-nope", {"mode": "on"})
    assert (status, error["error"]["code"]) == (404, "source_not_found")
    status, error = rig.client.request(
        "PUT", "/recordings/current/sources/in-usb-mic", {"mode": "loud"}
    )
    assert (status, error["error"]["code"]) == (422, "invalid_mode")
    rig.client.request("POST", "/recordings/current/stop")
    status, error = rig.client.request("GET", "/recordings/current/sources")
    assert (status, error["error"]["code"]) == (404, "no_active_recording")


def test_sources_are_published_as_events(rig: Rig) -> None:
    client = rig.app.events.subscribe()
    rig.client.request("POST", "/recordings", {})
    rig.client.request("POST", "/recordings/current/stop")

    events = []
    while not client.empty():
        events.append(client.get_nowait())

    sources = [data for event, data in events if event == "sources"]
    assert sources and _ids(sources[-1]) == ["in-headset-mic", "in-usb-mic", "out-speakers"]
    assert sources[-1]["id"] is not None


def test_no_device_at_all_is_audio_unavailable(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vozata.recorder.app.resolve_sources", lambda *args: [])

    status, error = rig.client.request("POST", "/recordings", {})

    assert (status, error["error"]["code"]) == (503, "audio_unavailable")


def test_a_chosen_device_that_is_gone_is_device_not_found(rig: Rig) -> None:
    status, error = rig.client.request("POST", "/recordings", {"mic_device_id": 99})

    assert (status, error["error"]["code"]) == (404, "device_not_found")


def test_pair_mode_has_no_sources_to_set(tmp_path: Path) -> None:
    rig = Rig(tmp_path, capture="pair")
    try:
        rig.client.request("POST", "/recordings", {})
        status, body = rig.client.request("GET", "/recordings/current/sources")
        assert (status, body["items"]) == (200, [])
        status, error = rig.client.request(
            "PUT", "/recordings/current/sources/in-x", {"mode": "on"}
        )
        assert (status, error["error"]["code"]) == (409, "sources_not_recorded")
        rig.client.request("POST", "/recordings/current/stop")
    finally:
        rig.close()


def test_start_up_continues_every_saved_source(rig: Rig) -> None:
    specs = resolve_sources(lambda function: function(), FakePyAudio(), None, None)
    recording = Recording.create(
        live_dir(rig.tmp),
        rig.settings,
        {spec.kind: spec.device for spec in specs if spec.preferred},
        lambda device, clock: FakeAudioSource(),
        rig.app,
        wall_clock=rig.wall,
        sources=specs,
    )
    recording.start()
    recording.manifest.last_heartbeat_at = rig.wall().isoformat(timespec="seconds")
    recording.save()
    recording._capture.stop_sources()  # type: ignore[union-attr]  # the recorder dies
    for track in recording._all_tracks():
        track._closed.set()
    rig.wall.now += timedelta(seconds=5)

    rig.app.start_up()

    current = rig.app.current
    assert current is not None and current.id == recording.id
    assert current.summary()["incarnation"] == 2
    sources = current.sources()
    assert sources is not None and [s["id"] for s in sources] == [
        "in-headset-mic",
        "in-usb-mic",
        "out-speakers",
    ]
    assert [s["preferred"] for s in sources] == [True, False, True]
    rig.client.request("POST", "/recordings/current/stop")
