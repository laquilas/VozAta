from __future__ import annotations

from tests.api.conftest import Api


def test_the_meeting_terms_given_at_start_reach_the_session(api: Api) -> None:
    response = api.client.post("/sessions", json={"vocabulary": ["Jéssica", "N5 Sensors"]})

    assert response.status_code == 201
    assert api.factory.sessions[0].options.vocabulary == ("Jéssica", "N5 Sensors")


def test_start_without_terms_passes_no_terms(api: Api) -> None:
    api.client.post("/sessions", json={})

    assert api.factory.sessions[0].options.vocabulary == ()


def test_get_without_a_file_is_an_empty_list(api: Api) -> None:
    response = api.client.get("/vocabulary")

    assert (response.status_code, response.json()) == (200, {"terms": []})


def test_put_then_get_round_trips_the_cleaned_terms(api: Api) -> None:
    put = api.client.put("/vocabulary", json={"terms": [" Avalonia ", "avalonia", "", "Jéssica"]})
    got = api.client.get("/vocabulary")

    assert (put.status_code, put.json()) == (200, {"terms": ["Avalonia", "Jéssica"]})
    assert got.json() == {"terms": ["Avalonia", "Jéssica"]}
    assert api.vocabulary_file.read_text("utf-8") == "Avalonia\nJéssica\n"


def test_get_reads_a_hand_edited_file(api: Api) -> None:
    api.vocabulary_file.write_text("# team\nN5 Sensors\n\nVozAta\n", "utf-8")

    assert api.client.get("/vocabulary").json() == {"terms": ["N5 Sensors", "VozAta"]}


def test_put_rejects_a_malformed_body(api: Api) -> None:
    response = api.client.put("/vocabulary", json={"terms": "Avalonia"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_a_folder_in_place_of_the_file_reads_empty_and_cannot_be_saved(api: Api) -> None:
    api.vocabulary_file.mkdir()  # a folder where the file should be

    got = api.client.get("/vocabulary")
    put = api.client.put("/vocabulary", json={"terms": ["x"]})

    assert (got.status_code, put.status_code) == (200, 503)  # a folder reads as no file
    assert put.json()["error"]["code"] == "vocabulary_failed"
    assert "could not be read or saved" in put.json()["error"]["message"]


def test_a_badly_encoded_file_is_503(api: Api) -> None:
    api.vocabulary_file.write_bytes(b"\xff\xfe\xfa")

    response = api.client.get("/vocabulary")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "vocabulary_failed"
