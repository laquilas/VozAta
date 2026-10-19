"""`GET /sessions/{id}/bundle` (phase 39): a meeting as a ZIP of its session folder."""

from __future__ import annotations

import io
import tempfile
import wave
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.api.conftest import Api
from tests.api.test_audio import MIC, database, recorded  # noqa: F401 - fixtures


def test_the_bundle_is_the_session_folder_with_both_tracks(api: Api, recorded: str) -> None:  # noqa: F811
    response = api.client.get(f"/sessions/{recorded}/bundle")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f'filename="{recorded}.zip"' in response.headers["content-disposition"]
    with ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {
            f"{recorded}/session.json",
            f"{recorded}/mic.wav",
            f"{recorded}/system.wav",
        } <= names
        assert f"{recorded}/mixed.wav" not in names
        with wave.open(io.BytesIO(archive.read(f"{recorded}/mic.wav"))) as mic:
            assert mic.getnframes() == len(MIC)


def test_the_temporary_folder_is_removed_after_sending(
    api: Api,
    recorded: str,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()

    assert api.client.get(f"/sessions/{recorded}/bundle").status_code == 200

    assert list((tmp_path / "temp").iterdir()) == []


def test_the_bundle_of_an_unknown_session_is_404(api: Api) -> None:
    response = api.client.get("/sessions/20991231_000000/bundle")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_the_bundle_of_the_session_being_recorded_is_409(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    response = api.client.get(f"/sessions/{session_id}/bundle")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_still_active"
