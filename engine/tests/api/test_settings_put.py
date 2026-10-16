from __future__ import annotations

from tests.api.conftest import Api


def test_a_valid_update_is_saved_and_returned(api: Api) -> None:
    api.env_file.write_text("# comment\nCHUNK_SECONDS=5\n", encoding="utf-8")

    response = api.client.put(
        "/settings", json={"values": {"CHUNK_SECONDS": 8, "MIX_MODE": "stereo"}}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] == []
    assert (body["values"]["CHUNK_SECONDS"], body["values"]["MIX_MODE"]) == (8.0, "stereo")
    assert api.env_file.read_text(encoding="utf-8").startswith("# comment\nCHUNK_SECONDS=8\n")
    assert api.client.get("/settings").json()["values"]["CHUNK_SECONDS"] == 8.0


def test_restart_keys_are_reported(api: Api) -> None:
    response = api.client.put("/settings", json={"values": {"WHISPER_MODEL": "medium"}})

    assert response.json()["restart_required"] == ["WHISPER_MODEL"]


def test_an_invalid_value_is_a_422_naming_the_key(api: Api) -> None:
    response = api.client.put("/settings", json={"values": {"CHUNK_SECONDS": 500}})

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["code"], error["key"]) == ("invalid_setting", "CHUNK_SECONDS")
    assert "CHUNK_SECONDS" in error["message"]
    assert not api.env_file.exists()


def test_an_unknown_key_is_a_422(api: Api) -> None:
    response = api.client.put("/settings", json={"values": {"NOPE": 1}})

    assert response.status_code == 422
    assert response.json()["error"]["key"] == "NOPE"


def test_a_malformed_body_is_rejected(api: Api) -> None:
    response = api.client.put("/settings", json={"CHUNK_SECONDS": 8})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_a_settings_file_that_cannot_be_written_is_a_503(api: Api, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from vozata import settings_file as module

    def locked(*args: object, **kwargs: object) -> object:
        raise PermissionError("locked by OneDrive")

    monkeypatch.setattr(module, "set_key", locked)
    monkeypatch.setattr(module, "WRITE_RETRY_SECONDS", 0)

    response = api.client.put("/settings", json={"values": {"CHUNK_SECONDS": 8}})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "settings_write_failed"
    assert "locked by OneDrive" in error["message"]
