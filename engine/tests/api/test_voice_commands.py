"""`GET|PUT /voice-commands` (phase 50)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.api.conftest import Api


def _use(api: Api, path: Path) -> None:
    api.app.state.container = dataclasses.replace(
        api.app.state.container, voice_commands_file=lambda: path
    )


def test_get_gives_the_defaults_until_a_list_is_saved(api: Api, tmp_path: Path) -> None:
    _use(api, tmp_path / "voice_commands.json")

    first = api.client.get("/voice-commands").json()
    saved = api.client.put(
        "/voice-commands",
        json={"commands": [{"phrase": " recap ", "action": "ask", "question": "What happened?"}]},
    )
    second = api.client.get("/voice-commands").json()

    assert first["commands"] == first["defaults"]
    assert first["defaults"][0] == {
        "phrase": "make the minutes",
        "action": "minutes",
        "question": None,
    }
    assert saved.status_code == 200
    assert second["commands"] == [
        {"phrase": "recap", "action": "ask", "question": "What happened?"}
    ]
    assert second["defaults"] == first["defaults"]


def test_an_invalid_list_is_refused_with_the_reason(api: Api, tmp_path: Path) -> None:
    _use(api, tmp_path / "voice_commands.json")

    response = api.client.put(
        "/voice-commands", json={"commands": [{"phrase": "x", "action": "ask"}]}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_voice_commands"
    assert "question" in error["message"]


def test_an_unwritable_place_is_reported(api: Api, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    _use(api, blocker / "voice_commands.json")  # a folder that is a file

    response = api.client.put(
        "/voice-commands", json={"commands": [{"phrase": "x", "action": "minutes"}]}
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "voice_commands_failed",
    )
