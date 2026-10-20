"""`POST /sessions/{id}/recover` and `recovery_available` (phase 17)."""

from __future__ import annotations

import threading
from collections.abc import Collection, Iterator
from pathlib import Path

import pytest

from tests.api.conftest import Api, RecordingBroadcaster, make_manager
from tests.test_session_recover import make_session_folder
from vozata.domain import Channel, SessionStatus
from vozata.ports import SessionObserver
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery


class _FinishingSession:
    """Stands in for `RecordingSession.recover`: status events, an optional gate, `done`."""

    def __init__(
        self, store: FileSessionRepository, observer: SessionObserver, gate: threading.Event
    ):
        self.store = store
        self.observer = observer
        self.gate = gate

    def recover(self, session_id: str, duration_seconds: float) -> None:
        self.observer.on_status(SessionStatus.FINALIZING, duration_seconds)
        assert self.gate.wait(5)
        self.store.write_meta(session_id, {**self.store.read_meta(session_id), "status": "done"})
        self.observer.on_status(SessionStatus.DONE, duration_seconds)


class _Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.api = Api(tmp_path, recovery=self._recovery)

    def _recovery(self, store: FileSessionRepository) -> SessionRecovery:
        def build(session_id: str, observer: SessionObserver) -> _FinishingSession:
            return _FinishingSession(store, observer, self.gate)

        return SessionRecovery(store, [FileAudioStore(store.store, 16000), store], build)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    rig = _Rig(tmp_path)
    with rig.api.client:
        yield rig
    rig.gate.set()
    for _ in range(500):  # a recovery a test left running ends once the gate opens
        if rig.api.manager._recovering is None:
            break
        threading.Event().wait(0.01)


def test_connect_offers_the_sessions_a_crash_cut_short(rig: _Rig) -> None:
    store = rig.api.store
    crashed = make_session_folder(store, status="recording")
    older = make_session_folder(store, status="interrupted")
    make_session_folder(store, status="done")

    with rig.api.client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["data"] == {"status": "idle"}
        offer = ws.receive_json()

    assert offer == {
        "type": "recovery_available",
        "session_id": None,
        "data": {"session_ids": sorted([crashed, older], reverse=True)},
    }
    assert store.read_meta(crashed)["status"] == "interrupted"


def test_connect_without_interrupted_sessions_sends_no_offer(rig: _Rig) -> None:
    make_session_folder(rig.api.store, status="done")

    with rig.api.client.websocket_connect("/ws") as ws:
        ws.receive_json()  # status
        rig.api.client.post("/sessions", json={})
        assert ws.receive_json()["type"] == "status"  # the new recording, not an offer
        rig.api.client.post("/sessions/current/stop")


def test_the_live_session_is_never_offered(rig: _Rig) -> None:
    live = rig.api.client.post("/sessions", json={}).json()["id"]

    assert rig.api.manager.interrupted_sessions() == []
    assert rig.api.store.read_meta(live)["status"] == "recording"
    rig.api.client.post("/sessions/current/stop")


def test_recover_returns_202_and_reports_progress_through_status_events(rig: _Rig) -> None:
    session_id = make_session_folder(rig.api.store, status="interrupted")

    response = rig.api.client.post(f"/sessions/{session_id}/recover")

    assert response.status_code == 202
    assert rig.api.manager.wait_until_finished(5)
    assert rig.api.broadcaster.of("status") == [
        (session_id, {"status": "finalizing", "duration_seconds": 1.0}),
        (session_id, {"status": "done", "duration_seconds": 1.0}),
    ]
    assert rig.api.store.read_meta(session_id)["status"] == "done"
    second = rig.api.client.post(f"/sessions/{session_id}/recover")
    assert (second.status_code, second.json()["error"]["code"]) == (409, "session_not_interrupted")


def test_recover_refuses_unknown_and_not_interrupted_sessions(rig: _Rig) -> None:
    done = make_session_folder(rig.api.store, status="done")

    not_interrupted = rig.api.client.post(f"/sessions/{done}/recover")
    unknown = rig.api.client.post("/sessions/20990101_000000/recover")

    assert not_interrupted.status_code == 409
    assert not_interrupted.json()["error"] == {
        "code": "session_not_interrupted",
        "message": f'Session "{done}" was not interrupted, so there is nothing to recover.',
    }
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "session_not_found")


def test_a_recovery_holds_the_single_session_slot(rig: _Rig) -> None:
    first = make_session_folder(rig.api.store, status="interrupted")
    second = make_session_folder(rig.api.store, status="interrupted")
    rig.gate.clear()

    assert rig.api.client.post(f"/sessions/{first}/recover").status_code == 202
    start = rig.api.client.post("/sessions", json={})
    again = rig.api.client.post(f"/sessions/{second}/recover")
    offered = rig.api.manager.interrupted_sessions()
    rig.gate.set()

    assert (start.status_code, start.json()["error"]["code"]) == (409, "session_already_active")
    assert (again.status_code, again.json()["error"]["code"]) == (409, "session_already_active")
    assert offered == [second]  # the one being recovered is live
    assert rig.api.manager.wait_until_finished(5)


def test_no_recovery_while_recording(rig: _Rig) -> None:
    session_id = make_session_folder(rig.api.store, status="interrupted")
    rig.api.client.post("/sessions", json={})

    response = rig.api.client.post(f"/sessions/{session_id}/recover")

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "session_already_active",
    )
    rig.api.client.post("/sessions/current/stop")


def test_a_failed_repair_sends_a_localized_error_and_frees_the_slot(rig: _Rig) -> None:
    store = rig.api.store
    session_id = make_session_folder(store, status="interrupted")
    store.paths(session_id).wav(Channel.SYSTEM).write_bytes(b"garbage")

    assert rig.api.client.post(f"/sessions/{session_id}/recover").status_code == 202
    assert rig.api.manager.wait_until_finished(5)

    [(event_session, data)] = rig.api.broadcaster.of("error")
    assert event_session == session_id
    assert data["code"] == "recovery_failed"
    assert data["message"].startswith(f'Session "{session_id}" could not be recovered (')
    assert store.read_meta(session_id)["status"] == "interrupted"
    assert rig.api.client.post("/sessions", json={}).status_code == 201
    rig.api.client.post("/sessions/current/stop")


def test_without_recovery_nothing_is_offered_or_recovered(api: Api) -> None:
    session_id = make_session_folder(api.store, status="interrupted")

    assert api.manager.interrupted_sessions() == []
    response = api.client.post(f"/sessions/{session_id}/recover")
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "session_not_interrupted",
    )


class _BrokenRecovery:
    def find_interrupted(self, live_ids: Collection[str] = ()) -> list[str]:
        raise OSError("disk unplugged")

    def is_interrupted(self, session_id: str) -> bool:
        return True

    def recover(self, session_id: str, observer: SessionObserver) -> bool:
        raise RuntimeError("boom")


def test_manager_failures_are_logged_and_reported_without_a_localizer(
    store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    manager = make_manager(
        lambda observer, options: None,  # type: ignore[arg-type]
        store,
        broadcaster,
        recovery=_BrokenRecovery(),
    )

    assert manager.interrupted_sessions() == []
    manager.recover("20261015_202358")
    assert manager.wait_until_finished(5)

    assert broadcaster.of("error") == [
        ("20261015_202358", {"code": "recovery_failed", "message": "boom"})
    ]
