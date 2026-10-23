"""`GET /sessions/{id}/requests` (phase 59)."""

from __future__ import annotations

import dataclasses

from tests.api.conftest import Api
from vozata.api.partial_minutes_job import PartialRequest
from vozata.api.request_log import RequestLog
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


def _with_log(api: Api, **fields: object) -> RequestLog:
    log = RequestLog(api.store, api.broadcaster)
    api.app.state.container = dataclasses.replace(api.app.state.container, requests=log, **fields)
    return log


def _done_session(api: Api) -> str:
    session_id = api.store.create()
    api.store.write_meta(session_id, {"id": session_id, "status": "done"})
    return session_id


def _kinds(api: Api, session_id: str) -> list[tuple[str, str, str, str | None]]:
    return [
        (entry.kind, entry.source, entry.status, entry.message)
        for entry in api.store.read_requests(session_id)
    ]


def test_minutes_again_refused_are_in_the_history(api: Api) -> None:
    session_id = _done_session(api)
    _with_log(api, regenerate_minutes=lambda session_id, template: False)

    assert api.client.post(f"/sessions/{session_id}/minutes").status_code == 409

    assert _kinds(api, session_id) == [("minutes", "app", "ignored", "session_still_active")]


def test_action_items_queued_are_running_in_the_history(api: Api) -> None:
    session_id = _done_session(api)
    _with_log(api, extract_action_items=lambda session_id: True)

    assert api.client.post(f"/sessions/{session_id}/action-items").status_code == 202

    assert _kinds(api, session_id) == [("action_items", "app", "running", None)]


def test_action_items_refused_are_ignored(api: Api) -> None:
    session_id = _done_session(api)
    _with_log(api, extract_action_items=lambda session_id: False)

    assert api.client.post(f"/sessions/{session_id}/action-items").status_code == 409

    assert _kinds(api, session_id) == [("action_items", "app", "ignored", "session_still_active")]


class _Busy:
    def start(self, answer_id: str, question: str, session_id: str | None) -> bool:
        return False


def test_a_question_about_a_meeting_is_in_its_history(api: Api) -> None:
    session_id = _done_session(api)
    _with_log(api, ask=_Busy())

    response = api.client.post("/ask", json={"question": " Who? ", "session_id": session_id})

    assert response.status_code == 409
    [entry] = api.store.read_requests(session_id)
    assert (entry.kind, entry.text, entry.status, entry.message) == (
        "ask",
        "Who?",
        "ignored",
        "answer_in_progress",
    )


class _BusyPartial:
    def start(self, request: PartialRequest) -> str | None:
        self.request = request
        return None


def test_minutes_of_a_range_refused_are_ignored(api: Api) -> None:
    session_id = _done_session(api)
    job = _BusyPartial()
    _with_log(api, partial_minutes=job)

    response = api.client.post(f"/sessions/{session_id}/partial-minutes", json={"end": 10})

    assert response.status_code == 409
    assert _kinds(api, session_id) == [
        ("range_minutes", "range", "ignored", "partial_minutes_in_progress")
    ]
    assert job.request.request_id == api.store.read_requests(session_id)[0].id
