"""PATCH /sessions/{id} with the options of a meeting being recorded (phase 63)."""

from __future__ import annotations

from tests.api.conftest import Api
from vozata.domain import ConversationLanguage


def test_options_change_while_recording_and_an_event_says_what(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    reply = api.client.patch(
        f"/sessions/{session_id}",
        json={
            "language": "pt",
            "vocabulary": ["VozAta"],
            "template": "daily",
            "translate_to": "es",
            "live_transcription": False,
            "generate_minutes": False,
        },
    )

    assert reply.status_code == 200
    changes = api.factory.sessions[-1].applied[-1]
    assert changes.language is ConversationLanguage.PT
    assert changes.vocabulary == ("VozAta",)
    assert (changes.template, changes.translate_to) == ("daily", "es")
    assert (changes.live_transcription, changes.generate_minutes) == (False, False)
    assert changes.title_set is False
    meta = api.store.read_meta(session_id)
    assert (meta["template"], meta["generate_minutes"]) == ("daily", False)
    events = api.broadcaster.of("session_updated")
    assert events[-1][0] == session_id
    assert events[-1][1]["language"] == "pt"


def test_a_title_with_options_is_normalized(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    api.client.patch(f"/sessions/{session_id}", json={"title": "  A   B ", "language": "en"})

    changes = api.factory.sessions[-1].applied[-1]
    assert (changes.title_set, changes.title) == (True, "A B")


def test_an_unknown_template_is_refused(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    reply = api.client.patch(f"/sessions/{session_id}", json={"template": "nope"})

    assert (reply.status_code, reply.json()["error"]["code"]) == (422, "unknown_template")


def test_an_empty_change_is_refused(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    assert api.client.patch(f"/sessions/{session_id}", json={}).status_code == 422


def test_a_finished_meeting_takes_only_title_template_and_minutes_flag(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]
    api.client.post("/sessions/current/stop")
    assert api.manager.wait_until_finished(5)

    ok = api.client.patch(
        f"/sessions/{session_id}",
        json={"template": "daily", "generate_minutes": True, "title": "X"},
    )
    refused = api.client.patch(f"/sessions/{session_id}", json={"language": "pt"})

    assert ok.status_code == 200
    meta = api.store.read_meta(session_id)
    assert (meta["template"], meta["generate_minutes"], meta["title"]) == ("daily", True, "X")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "session_not_live")


def test_an_unknown_meeting_is_not_found(api: Api) -> None:
    reply = api.client.patch("/sessions/20200101_000000", json={"template": "daily"})

    assert reply.status_code == 404
