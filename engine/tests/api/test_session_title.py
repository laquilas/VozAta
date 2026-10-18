"""Meeting titles over the API (phase 35): start, summary and `PATCH /sessions/{id}`."""

from __future__ import annotations

from tests.api.conftest import Api

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
