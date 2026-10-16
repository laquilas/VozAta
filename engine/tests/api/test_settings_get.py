from __future__ import annotations

import dataclasses

import pytest

from tests.api.conftest import Api
from vozata import settings_view
from vozata.config import KEYS


def test_settings_returns_every_key_with_its_schema(api: Api) -> None:
    response = api.client.get("/settings")

    assert response.status_code == 200
    body = response.json()
    assert set(body["values"]) == set(KEYS)
    assert [item["key"] for item in body["schema"]] == list(KEYS)
    assert body["values"]["API_PORT"] == 8765
    mix = next(item for item in body["schema"] if item["key"] == "MIX_MODE")
    assert mix == {
        "key": "MIX_MODE",
        "type": "choice",
        "default": "mono",
        "choices": ["mono", "stereo"],
        "secret": False,
    }


def test_secret_settings_are_masked(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    fields = list(settings_view.FIELDS)
    index = next(i for i, field in enumerate(fields) if field.key == "OLLAMA_MODEL")
    fields[index] = dataclasses.replace(fields[index], secret=True)
    monkeypatch.setattr(settings_view, "FIELDS", tuple(fields))

    body = api.client.get("/settings").json()

    assert body["values"]["OLLAMA_MODEL"] == "********"
    assert "qwen" not in str(body["values"])
