"""The session routes when the recorder process records (phase 61)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.api.conftest import Api
from vozata.domain import SessionStatus
from vozata.recorder_client import RecorderApiError, RecorderUnavailableError


class FakeLink:
    def __init__(self, api: Api) -> None:
        self.api = api
        self.available = True
        self.follows = False
        self.calls: list[tuple[str, Any]] = []
        self.error: Exception | None = None
        self.linked: set[str] = set()

    def recorder_available(self) -> bool:
        return self.available

    def recorder_health(self) -> dict[str, Any] | None:
        if not self.available:
            return None
        return {"recorder": "ok", "recording": {"id": "20261103_101500", "status": "paused"}}

    def following(self) -> str | None:
        current = self.api.manager.current
        return current.id if self.follows and current is not None else None

    def start_recording(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start", body))
        if self.error is not None:
            raise self.error
        return {
            "id": "20261103_101500",
            "status": "recording",
            "started_at": None,
            "ended_at": None,
            "duration_seconds": 0.0,
            "language": None,
            "has_minutes": False,
        }

    def _control(self, name: str) -> None:
        self.calls.append((name, None))
        if self.error is not None:
            raise self.error

    def pause(self) -> None:
        self._control("pause")

    def resume(self) -> None:
        self._control("resume")

    def stop(self) -> None:
        self._control("stop")

    def mirror_title(self, title: str | None) -> None:
        self.calls.append(("title", title))

    def linked_sessions(self) -> set[str]:
        return self.linked

    def start(self) -> None:
        self.calls.append(("thread", "start"))

    def close(self) -> None:
        self.calls.append(("thread", "close"))


@pytest.fixture
def linked(tmp_path: Path) -> Iterator[tuple[Api, FakeLink]]:
    holder: list[FakeLink] = []

    def make(api: Api) -> FakeLink:
        holder.append(FakeLink(api))
        return holder[0]

    api = Api(tmp_path, recorder_link=make)
    with api.client:
        yield api, holder[0]
    current = api.manager.current
    if current is not None and current.status in (SessionStatus.RECORDING, SessionStatus.PAUSED):
        api.manager.stop()
    assert api.manager.wait_until_finished(5)


def test_the_link_runs_with_the_app(linked: tuple[Api, FakeLink]) -> None:
    _, link = linked

    assert link.calls[0] == ("thread", "start")


def test_start_goes_to_the_recorder_with_the_normalized_title(
    linked: tuple[Api, FakeLink],
) -> None:
    api, link = linked

    reply = api.client.post(
        "/sessions", json={"mic_device_id": 15, "title": "  Weekly   sync ", "language": "pt"}
    )

    assert reply.status_code == 201
    assert link.calls[-1] == (
        "start",
        {"mic_device_id": 15, "title": "Weekly sync", "language": "pt"},
    )
    assert api.manager.current is None  # the engine opened no device


@pytest.mark.parametrize(
    ("code", "status", "engine_code"),
    [
        ("device_not_found", 404, "device_not_found"),
        ("recording_already_active", 409, "session_already_active"),
        ("audio_unavailable", 503, "recorder_failed"),
    ],
)
def test_recorder_errors_become_engine_errors(
    linked: tuple[Api, FakeLink], code: str, status: int, engine_code: str
) -> None:
    api, link = linked
    link.error = RecorderApiError(503, code, "nope")

    reply = api.client.post("/sessions", json={})

    assert (reply.status_code, reply.json()["error"]["code"]) == (status, engine_code)


def test_without_a_recorder_the_engine_records_itself(linked: tuple[Api, FakeLink]) -> None:
    api, link = linked
    link.available = False

    assert api.client.post("/sessions", json={}).status_code == 201

    assert api.manager.current is not None
    assert [name for name, _ in link.calls] == ["thread"]


def test_a_recorder_gone_meanwhile_falls_back_to_the_engine(linked: tuple[Api, FakeLink]) -> None:
    api, link = linked
    link.error = RecorderUnavailableError("gone")

    assert api.client.post("/sessions", json={}).status_code == 201
    assert api.manager.current is not None


def test_controls_of_a_followed_recording_go_to_the_recorder(
    linked: tuple[Api, FakeLink],
) -> None:
    api, link = linked
    link.available = False
    session_id = api.client.post("/sessions", json={}).json()["id"]
    link.follows = True

    assert api.client.post("/sessions/current/pause").status_code == 200
    assert api.client.post("/sessions/current/resume").status_code == 200
    stopped = api.client.post("/sessions/current/stop")
    api.client.patch(f"/sessions/{session_id}", json={"title": "Renamed"})

    assert (stopped.status_code, stopped.json()["status"]) == (202, "finalizing")
    assert [name for name, _ in link.calls[1:]] == ["pause", "resume", "stop", "title"]
    assert link.calls[-1] == ("title", "Renamed")
    link.follows = False


def test_a_recorder_that_fails_a_control_is_reported(linked: tuple[Api, FakeLink]) -> None:
    api, link = linked
    link.available = False
    api.client.post("/sessions", json={})
    link.follows = True

    link.error = RecorderUnavailableError("gone")
    down = api.client.post("/sessions/current/pause")
    link.error = RecorderApiError(404, "no_active_recording", "none")
    gone = api.client.post("/sessions/current/stop")

    assert (down.status_code, down.json()["error"]["code"]) == (503, "recorder_failed")
    assert (gone.status_code, gone.json()["error"]["code"]) == (409, "no_active_session")
    link.follows = False


def test_unlinked_controls_and_renames_stay_in_the_engine(linked: tuple[Api, FakeLink]) -> None:
    api, link = linked
    link.available = False
    session_id = api.client.post("/sessions", json={}).json()["id"]

    api.client.patch(f"/sessions/{session_id}", json={"title": "Engine only"})
    assert api.client.post("/sessions/current/pause").json()["status"] == "paused"

    assert [name for name, _ in link.calls] == ["thread"]


def test_health_says_whether_the_recorder_answers(linked: tuple[Api, FakeLink]) -> None:
    api, link = linked

    up = api.client.get("/health").json()["recorder"]
    link.available = False
    down = api.client.get("/health").json()["recorder"]

    assert up == {"reachable": True, "port": 8769, "recording_id": "20261103_101500"}
    assert down == {"reachable": False, "port": 8769, "recording_id": None}


def test_health_without_the_recorder(api: Api) -> None:
    assert api.client.get("/health").json()["recorder"] is None
