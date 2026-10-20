"""Meeting titles over the API (phase 35): start, summary and `PATCH /sessions/{id}`."""

from __future__ import annotations

import pytest

from tests.api.conftest import Api, hold_in_queue

SESSION = "20261015_202358"


def _start(api: Api, **body: object):  # type: ignore[no-untyped-def]
    return api.client.post("/sessions", json=body)


def test_start_without_a_title_is_untitled(api: Api) -> None:
    started = _start(api)

    assert started.status_code == 201
    assert started.json()["title"] is None
    assert api.factory.sessions[0].options.title is None
    assert "title" not in api.store.read_meta(SESSION)


def test_start_with_a_title_trims_it_and_stores_it(api: Api) -> None:
    started = _start(api, title="  Weekly\n sync  ")

    assert started.json()["title"] == "Weekly sync"
    assert api.factory.sessions[0].options.title == "Weekly sync"
    assert api.store.read_meta(SESSION)["title"] == "Weekly sync"
    listed = api.client.get("/sessions").json()["items"][0]
    assert listed["title"] == "Weekly sync"
    assert api.client.get(f"/sessions/{SESSION}").json()["title"] == "Weekly sync"


def test_a_blank_title_is_untitled(api: Api) -> None:
    started = _start(api, title="   ")

    assert started.json()["title"] is None
    assert api.factory.sessions[0].options.title is None


def test_a_title_longer_than_200_characters_is_422(api: Api) -> None:
    response = _start(api, title="x" * 201)

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "title_too_long",
        "message": "The title can have at most 200 characters.",
    }
    assert api.factory.sessions == []


def test_a_title_of_200_characters_is_accepted(api: Api) -> None:
    assert _start(api, title="x" * 200).status_code == 201


# PATCH /sessions/{id}


def _rename(api: Api, title: object, session_id: str = SESSION):  # type: ignore[no-untyped-def]
    return api.client.patch(f"/sessions/{session_id}", json={"title": title})


def test_patch_while_recording_renames_the_live_session(api: Api) -> None:
    _start(api)

    renamed = _rename(api, "  Planning ")

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Planning"
    assert renamed.json()["status"] == "recording"
    assert api.factory.sessions[0].calls[-1] == "set_title"
    assert api.store.read_meta(SESSION)["title"] == "Planning"


def test_patch_while_paused_renames_the_live_session(api: Api) -> None:
    _start(api, title="Draft")
    api.client.post("/sessions/current/pause")

    assert _rename(api, "Final").json()["title"] == "Final"
    assert api.factory.sessions[0].calls[-1] == "set_title"


def test_the_title_survives_the_end_of_the_recording(api: Api) -> None:
    _start(api, title="Draft")
    _rename(api, "Final")
    api.client.post("/sessions/current/stop")
    assert api.manager.wait_until_finished(5)

    assert api.client.get(f"/sessions/{SESSION}").json()["title"] == "Final"


def test_patch_after_the_recording_rewrites_the_stored_metadata(api: Api) -> None:
    _start(api, title="Draft")
    api.client.post("/sessions/current/stop")
    assert api.manager.wait_until_finished(5)
    before = api.store.read_meta(SESSION)

    renamed = _rename(api, "Retro")

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Retro"
    assert renamed.json()["status"] == "done"
    assert api.store.read_meta(SESSION) == {**before, "title": "Retro"}
    assert "set_title" not in api.factory.sessions[0].calls


@pytest.mark.parametrize("title", [None, "", "   "])
def test_patch_with_null_or_blank_clears_the_title(api: Api, title: str | None) -> None:
    _start(api, title="Draft")
    api.client.post("/sessions/current/stop")
    assert api.manager.wait_until_finished(5)

    renamed = _rename(api, title)

    assert renamed.json()["title"] is None
    assert api.client.get("/sessions").json()["items"][0]["title"] is None


def test_patch_of_an_unknown_session_is_404(api: Api) -> None:
    response = _rename(api, "Retro", "20991231_000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_patch_with_a_long_title_is_422_and_keeps_the_old_one(api: Api) -> None:
    _start(api, title="Draft")

    response = _rename(api, "x" * 201)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "title_too_long"
    assert api.store.read_meta(SESSION)["title"] == "Draft"


@pytest.mark.parametrize("body", [{}, {"title": "A", "status": "done"}, {"title": 3}])
def test_patch_rejects_other_fields_and_a_missing_title(api: Api, body: dict[str, object]) -> None:
    _start(api)

    response = api.client.patch(f"/sessions/{SESSION}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_patch_of_a_queued_session_is_allowed(api: Api) -> None:
    _start(api)
    api.client.post("/sessions/current/stop")
    assert api.manager.wait_until_finished(5)
    release = hold_in_queue(api.manager, SESSION)  # e.g. a recovery job

    response = _rename(api, "Retro")

    release.set()
    assert api.manager.wait_until_finished(5)
    assert response.status_code == 200
    assert api.store.read_meta(SESSION)["title"] == "Retro"
