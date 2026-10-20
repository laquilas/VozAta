"""`DELETE /sessions/{id}` (phase 36): permanent in SQLite, to the Recycle Bin for files."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

from tests.api.conftest import Api, hold_in_queue
from tests.fakes import FakeLocalizer
from tests.storage.repository_contract import RAW
from vozata.domain import ActionItem, StorageInfo, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

STARTED = datetime(2026, 10, 14, 9, 0).astimezone()


class RecordingSearch:
    """A `TranscriptSearch` that records what it was asked to index."""

    def __init__(self) -> None:
        self.indexed: list[tuple[str, list[TranscriptSegment]]] = []

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        self.indexed.append((session_id, list(segments)))

    def search(self, query: str, limit: int = 50) -> list:  # type: ignore[type-arg]
        return []


def _full(api: Api, started: datetime = STARTED) -> str:
    """A finished meeting with transcript, minutes, speakers and action items."""
    store = api.store
    session_id = store.create(started)
    store.write_meta(
        session_id, {"id": session_id, "status": "done", "started_at": started.isoformat()}
    )
    sink = store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for segment in RAW:
        sink.emit(segment)
    sink.close()
    store.write_minutes(session_id, "# Minutes\n")
    store.write_speakers(session_id, ["system:1"])
    store.write_action_items(session_id, [ActionItem("a1", "Send the deck")])
    return session_id


def _use_search(api: Api) -> RecordingSearch:
    search = RecordingSearch()
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=search)
    return search


def test_delete_moves_the_folder_to_the_recycle_bin_and_clears_the_search(api: Api) -> None:
    search = _use_search(api)
    session_id = _full(api)
    folder = api.store.paths(session_id).root

    response = api.client.delete(f"/sessions/{session_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert api.recycler.recycled == [folder]
    assert not folder.exists()
    assert search.indexed == [(session_id, [])]
    assert api.client.get(f"/sessions/{session_id}").status_code == 404
    assert api.client.get("/sessions").json()["total"] == 0


def test_delete_in_the_database_is_permanent(api: Api, tmp_path: Path) -> None:
    database = Database(tmp_path / "vozata.db")
    store = SqliteSessionRepository(database, tmp_path / "db-recordings")
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, store=store, storage=StorageInfo("sqlite", database.path)
    )
    api.store = store  # type: ignore[assignment]
    api.manager._store = store  # the manager deletes through the same repository
    session_id = _full(api)

    response = api.client.delete(f"/sessions/{session_id}")

    assert response.status_code == 204
    assert store.list_sessions() == []
    assert not (tmp_path / "db-recordings" / session_id).exists()
    assert api.recycler.recycled == []  # nothing goes to the Recycle Bin
    assert database.connection().execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0
    database.close()


def test_delete_of_an_unknown_session_is_404(api: Api) -> None:
    response = api.client.delete("/sessions/20991231_000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize("pause", [False, True])
def test_delete_while_recording_or_paused_is_409(api: Api, pause: bool) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]
    if pause:
        api.client.post("/sessions/current/pause")

    response = api.client.delete(f"/sessions/{session_id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_still_active"
    assert session_id in response.json()["error"]["message"]
    assert api.recycler.recycled == []


def test_delete_while_finalizing_is_409_then_works_once_done(api: Api) -> None:
    api.factory.stop_gate = threading.Event()
    session_id = api.client.post("/sessions", json={}).json()["id"]
    api.client.post("/sessions/current/stop")

    assert api.client.delete(f"/sessions/{session_id}").status_code == 409

    api.factory.stop_gate.set()
    assert api.manager.wait_until_finished(5)
    assert api.client.delete(f"/sessions/{session_id}").status_code == 204


def test_delete_of_another_session_while_recording_works(api: Api) -> None:
    older = _full(api, datetime(2026, 10, 1, 9, 0).astimezone())
    api.client.post("/sessions", json={})

    assert api.client.delete(f"/sessions/{older}").status_code == 204


def test_delete_while_queued_or_recovering_is_409(api: Api) -> None:
    session_id = _full(api)
    release = hold_in_queue(api.manager, session_id)  # a recovery job (phase 17/40)

    response = api.client.delete(f"/sessions/{session_id}")

    release.set()
    assert api.manager._queue.wait_idle(5)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_still_active"


def test_a_recycle_bin_failure_is_a_500_and_keeps_the_session(api: Api) -> None:
    session_id = _full(api)
    api.recycler.error = PermissionError("mixed.wav is open in another program")

    response = api.client.delete(f"/sessions/{session_id}")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "session_delete_failed"
    assert "mixed.wav is open" in response.json()["error"]["message"]
    assert api.client.get(f"/sessions/{session_id}").status_code == 200
