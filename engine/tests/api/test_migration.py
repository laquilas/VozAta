"""`MigrationJob`, `GET /migration` and the migration events (phase 33)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tests.api.conftest import Api, RecordingBroadcaster
from tests.fakes import FakeLocalizer
from vozata.api.migration_job import MigrationJob
from vozata.storage.migration import MigrationError, NotEnoughSpaceError


class FakeImporter:
    def __init__(self, folders: list[str], bad: set[str] = frozenset(), short: str | None = None):
        self.folders = folders
        self.bad = bad
        self.short = short
        self.imported: list[str] = []
        self.recorded: list[MigrationError] = []
        self.gate: threading.Event | None = None

    def pending(self) -> list[str]:
        return list(self.folders)

    def import_one(self, session_id: str) -> MigrationError | None:
        if self.gate is not None:
            self.gate.wait(5)
        if session_id == self.short:
            raise NotEnoughSpaceError(f"/rec/{session_id}", 5 * 1024 * 1024 + 1, 3 * 1024 * 1024)
        if session_id in self.bad:
            error = MigrationError(f"/rec/{session_id}", "unreadable_json", "boom")
            self.recorded.append(error)
            return error
        self.imported.append(session_id)
        return None

    def errors(self) -> list[MigrationError]:
        return list(self.recorded)


def _job(importer: FakeImporter, broadcaster: RecordingBroadcaster, **options) -> MigrationJob:
    return MigrationJob(importer, broadcaster, FakeLocalizer(), **options)


def test_every_pending_folder_is_imported_with_progress_then_done() -> None:
    broadcaster = RecordingBroadcaster()
    importer = FakeImporter(["a", "b", "c"], bad={"b"})
    finished: list[bool] = []
    job = _job(importer, broadcaster, on_done=lambda: finished.append(True))

    job.run()

    assert importer.imported == ["a", "c"]
    assert broadcaster.of("migration_progress") == [
        (None, {"done": 0, "total": 3, "current": "a", "paused": False}),
        (None, {"done": 1, "total": 3, "current": "b", "paused": False}),
        (None, {"done": 2, "total": 3, "current": "c", "paused": False}),
    ]
    assert broadcaster.of("migration_done") == [
        (None, {"state": "done", "imported": 2, "skipped": 1, "errors": 1})
    ]
    assert finished == [True]
    summary = job.summary()
    assert summary["state"] == "done"
    assert (summary["done"], summary["total"], summary["current"]) == (3, 3, None)
    assert summary["errors"] == [
        {
            "folder": "/rec/b",
            "reason": "unreadable_json",
            "message": "migration.unreadable_json",
            "detail": "boom",
        }
    ]
    assert summary["message"] is None
    assert not job.is_running()


def test_nothing_pending_ends_at_once() -> None:
    broadcaster = RecordingBroadcaster()
    job = _job(FakeImporter([]), broadcaster)

    assert job.summary()["state"] == "idle"
    job.run()

    assert broadcaster.of("migration_progress") == []
    assert broadcaster.of("migration_done")[0][1]["state"] == "done"


def test_the_import_waits_while_a_session_is_busy() -> None:
    broadcaster = RecordingBroadcaster()
    importer = FakeImporter(["a"])
    busy = iter([True, True, False])
    waits: list[float] = []

    def wait(seconds: float) -> None:
        assert importer.imported == []  # nothing imported while busy
        waits.append(seconds)

    _job(importer, broadcaster, should_pause=lambda: next(busy), wait=wait).run()

    assert waits == [1.0, 1.0]
    assert [data["paused"] for _, data in broadcaster.of("migration_progress")] == [True, False]
    assert importer.imported == ["a"]


def test_a_short_disk_stops_the_import_with_a_localized_message() -> None:
    broadcaster = RecordingBroadcaster()
    importer = FakeImporter(["a", "b", "c"], short="b")
    job = _job(importer, broadcaster)

    job.run()

    assert importer.imported == ["a"]
    assert broadcaster.of("migration_done")[0][1] == {
        "state": "no_space",
        "imported": 1,
        "skipped": 0,
        "errors": 0,
    }
    summary = job.summary()
    assert summary["state"] == "no_space"
    assert (summary["needed_bytes"], summary["free_bytes"]) == (
        5 * 1024 * 1024 + 1,
        3 * 1024 * 1024,
    )
    assert summary["message"] == "migration.no_space(folder=/rec/b,free=3,needed=6)"


def test_an_unexpected_error_fails_the_job_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    broadcaster = RecordingBroadcaster()
    importer = FakeImporter(["a"])
    importer.pending = lambda: (_ for _ in ()).throw(RuntimeError("db gone"))  # type: ignore[method-assign]

    job = _job(importer, broadcaster)
    job.run()

    assert job.summary()["state"] == "failed"
    assert "Importing the session folders failed" in caplog.text


def test_a_failing_on_done_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> None:
        raise RuntimeError("no listeners")

    _job(FakeImporter([]), RecordingBroadcaster(), on_done=broken).run()

    assert "After the folder import" in caplog.text


def test_start_runs_in_the_background_and_wait_done_joins_it() -> None:
    importer = FakeImporter(["a"])
    importer.gate = threading.Event()
    job = _job(importer, RecordingBroadcaster())
    assert job.wait_done()  # not started: nothing to wait for

    job.start()
    assert not job.wait_done(0.05)
    assert job.is_running()
    importer.gate.set()

    assert job.wait_done(5)
    assert importer.imported == ["a"]


def test_get_migration_is_disabled_without_a_job(api: Api) -> None:
    response = api.client.get("/migration")

    assert response.status_code == 200
    assert response.json() == {
        "state": "disabled",
        "done": 0,
        "total": 0,
        "current": None,
        "paused": False,
        "imported": 0,
        "skipped": 0,
        "needed_bytes": None,
        "free_bytes": None,
        "message": None,
        "errors": [],
    }


def test_get_migration_returns_the_job_summary(tmp_path: Path) -> None:
    importer = FakeImporter(["a", "b"], bad={"b"})
    api = Api(tmp_path, migration=lambda rig: _job(importer, rig.broadcaster))

    _container_job(api).run()
    body = api.client.get("/migration").json()

    assert body["state"] == "done"
    assert (body["imported"], body["skipped"]) == (1, 1)
    assert body["errors"][0]["reason"] == "unreadable_json"


def test_connect_while_importing_sends_the_progress_after_the_status(tmp_path: Path) -> None:
    importer = FakeImporter(["a", "b"])
    importer.gate = threading.Event()
    api = Api(tmp_path, migration=lambda rig: _job(importer, rig.broadcaster))
    job = _container_job(api)
    job.start()
    deadline = time.monotonic() + 5
    while not job.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        with api.client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "status"
            progress = ws.receive_json()
    finally:
        importer.gate.set()
        job.wait_done(5)

    assert progress["type"] == "migration_progress"
    assert progress["data"]["total"] == 2


def test_connect_after_the_import_sends_only_the_status(tmp_path: Path) -> None:
    api = Api(tmp_path, migration=lambda rig: _job(FakeImporter([]), rig.broadcaster))
    job = _container_job(api)
    job.run()

    with api.client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "status"

    assert not job.is_running()  # so no `migration_progress` follows the status


def _container_job(api: Api) -> MigrationJob:
    return api.app.state.container.migration


def test_the_app_starts_the_import_when_it_starts(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    importer = FakeImporter(["a"])
    api = Api(tmp_path, migration=lambda rig: _job(importer, rig.broadcaster))

    with TestClient(api.app):  # runs the lifespan
        assert _container_job(api).wait_done(5)

    assert importer.imported == ["a"]
    assert api.broadcaster.of("migration_done")[0][1]["state"] == "done"
