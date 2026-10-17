from __future__ import annotations

from tests.api.conftest import Api


def test_the_meeting_terms_given_at_start_reach_the_session(api: Api) -> None:
    response = api.client.post("/sessions", json={"vocabulary": ["Jéssica", "N5 Sensors"]})

    assert response.status_code == 201
    assert api.factory.sessions[0].options.vocabulary == ("Jéssica", "N5 Sensors")


def test_start_without_terms_passes_no_terms(api: Api) -> None:
    api.client.post("/sessions", json={})

    assert api.factory.sessions[0].options.vocabulary == ()
