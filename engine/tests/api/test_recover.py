"""`POST /sessions/{id}/recover` and `recovery_available` (phase 17)."""

from __future__ import annotations

import threading
from collections.abc import Collection, Iterator
from pathlib import Path

import pytest

from tests.api.conftest import Api, RecordingBroadcaster, make_manager
from tests.session_folders import make_session_folder
from vozata.api.session_manager import session_observer
from vozata.domain import SessionStatus
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery


class _Rig:
    """The real app over fakes; a recovery job ends by marking the session `done`."""

    def __init__(self, tmp_path: Path) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.repaired: list[tuple[str, bool]] = []
        self.api = Api(tmp_path, recovery=self._recovery, jobs=self._jobs)

    def _recovery(self, store: FileSessionRepository) -> SessionRecovery:
        return SessionRecovery(store, [FileAudioStore(store.store, 16000), store])

    def _jobs(self, api: Api):  # type: ignore[no-untyped-def]
        def make(session_id: str, repair: bool, closed: threading.Event | None) -> ProcessingJob:
            self.repaired.append((session_id, repair))
            observer = session_observer(api.broadcaster, api.labeler, session_id)

            def step(token: object, progress: object) -> None:
                observer.on_status(SessionStatus.FINALIZING, 1.0)
                assert self.gate.wait(5)

            def finished() -> None:
                meta = api.store.read_meta(session_id)
                api.store.write_meta(session_id, {**meta, "status": "done"})
                observer.on_status(SessionStatus.DONE, 1.0)

            return ProcessingJob(session_id, (Step(StepKind.INDEX, 1.0, False, step),), finished)

        return make


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    rig = _Rig(tmp_path)
    with rig.api.client:
        yield rig
    rig.gate.set()
    rig.api.manager.wait_until_finished(5)  # a recovery a test left running ends once released


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
    assert rig.repaired == [(session_id, True)]  # the job starts with the repair step
    assert rig.api.broadcaster.of("status") == [
        (session_id, {"status": "finalizing", "duration_seconds": 1.0}),
        (session_id, {"status": "done", "duration_seconds": 1.0}),
    ]
    assert [d["state"] for sid, d in rig.api.broadcaster.of("processing")][-1] == "done"
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


def test_recover_enqueues_instead_of_taking_the_slot(rig: _Rig) -> None:
    first = make_session_folder(rig.api.store, status="interrupted")
    second = make_session_folder(rig.api.store, status="interrupted")
    rig.gate.clear()

    assert rig.api.client.post(f"/sessions/{first}/recover").status_code == 202
    start = rig.api.client.post("/sessions", json={})  # not refused: recovery is a queue job
    again = rig.api.client.post(f"/sessions/{second}/recover")
    offered = rig.api.manager.interrupted_sessions()
    rig.api.client.post("/sessions/current/stop")
    rig.gate.set()

    assert start.status_code == 201
    assert again.status_code == 202
    assert offered == []  # both are in the queue: not offered again
    assert rig.api.manager.wait_until_finished(5)
    assert [sid for sid, repair in rig.repaired if repair] == [first, second]


def test_recovering_a_session_already_queued_does_not_queue_it_twice(rig: _Rig) -> None:
    session_id = make_session_folder(rig.api.store, status="interrupted")
    rig.gate.clear()

    first = rig.api.client.post(f"/sessions/{session_id}/recover")
    again = rig.api.client.post(f"/sessions/{session_id}/recover")
    rig.gate.set()

    assert (first.status_code, again.status_code) == (202, 202)
    assert rig.api.manager.wait_until_finished(5)
    assert rig.repaired == [(session_id, True)]


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


def test_a_failing_search_for_interrupted_sessions_is_logged_and_offers_none(
    store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    manager = make_manager(
        lambda observer, options: None,  # type: ignore[arg-type]
        store,
        broadcaster,
        recovery=_BrokenRecovery(),
    )

    assert manager.interrupted_sessions() == []


def test_startup_resumes_unfinished_meetings_before_the_migration_starts_and_offers(
    tmp_path: Path,
) -> None:
    order: list[str] = []

    class _Migration:
        def start(self) -> None:
            order.append("migration")

        def is_running(self) -> bool:
            return False

    rig = _Rig(tmp_path)
    api = Api(tmp_path, recovery=rig._recovery, jobs=rig._jobs, migration=lambda a: _Migration())
    stopped = make_session_folder(
        api.store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    crashed = make_session_folder(api.store, status="recording")
    original = api.manager.resume_pending
    api.manager.resume_pending = lambda: order.append("resume") or original()  # type: ignore[method-assign]

    with api.client:
        assert api.manager.wait_until_finished(5)
        with api.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # status
            offer = ws.receive_json()

    assert order == ["resume", "migration"]
    assert rig.repaired == [(stopped, True)]
    assert api.store.read_meta(stopped)["status"] == "done"
    assert offer["data"] == {"session_ids": [crashed]}  # only the crash during capture
