"""`GET /sessions/{id}/requests` (phase 59)."""

from __future__ import annotations

from tests.api.conftest import Api
from vozata.domain import RequestEntry

ENTRY = RequestEntry(
    "r1", "2026-10-23T10:05:00-03:00", 312.5, "minutes_so_far", "voice", "gere a ata", "done", "p1"
)


def test_the_history_of_a_meeting_oldest_first(api: Api) -> None:
    session_id = api.store.create()
    api.store.write_meta(session_id, {"id": session_id, "status": "done"})
    later = RequestEntry("r2", "2026-10-23T10:06:00-03:00", None, "ask", "app", "Who?", "running")
    api.store.write_requests(session_id, [ENTRY, later])

    response = api.client.get(f"/sessions/{session_id}/requests")

    assert response.status_code == 200
    assert response.json() == {"items": [ENTRY.to_dict(), later.to_dict()]}


def test_an_unknown_meeting_is_not_found(api: Api) -> None:
    response = api.client.get("/sessions/20991231_000000/requests")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
