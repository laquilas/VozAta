from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.recorder.test_app import Rig
from vozata.api.app import _interrupted
from vozata.recorder_client import HttpRecorderClient, RecorderApiError, RecorderUnavailableError


@pytest.fixture
def rig(tmp_path: Path):  # type: ignore[no-untyped-def]
    rig = Rig(tmp_path)
    yield rig
    rig.close()


def test_the_client_drives_a_real_recorder(rig: Rig) -> None:
    client = HttpRecorderClient(rig.server.port)

    assert client.health()["recorder"] == "ok"  # type: ignore[index]
    started = client.start({"options": {"language": "pt"}})
    assert client.pause()["status"] == "paused"
    assert client.resume()["status"] == "recording"
    assert client.update_options({"title": "A"})["options"]["title"] == "A"
    assert client.stop()["status"] == "stopped"
    assert started["id"] == "20261103_101500"


def test_recorder_errors_carry_their_code(rig: Rig) -> None:
    client = HttpRecorderClient(rig.server.port)

    with pytest.raises(RecorderApiError) as error:
        client.stop()

    assert (error.value.status, error.value.code) == (404, "no_active_recording")


def test_a_recorder_that_does_not_answer() -> None:
    client = HttpRecorderClient(1, timeout=0.2)

    assert client.health() is None
    with pytest.raises(RecorderUnavailableError):
        client.pause()


def test_recovery_never_offers_a_meeting_a_recording_rebuilds() -> None:
    manager = SimpleNamespace(interrupted_sessions=lambda: ["a", "b"])
    link = SimpleNamespace(linked_sessions=lambda: {"b"})

    assert _interrupted(SimpleNamespace(manager=manager, recorder_link=None)) == ["a", "b"]  # type: ignore[arg-type]
    assert _interrupted(SimpleNamespace(manager=manager, recorder_link=link)) == ["a"]  # type: ignore[arg-type]
