"""`GET /sessions/{id}/bundle` (phase 39): a meeting as a ZIP of its session folder."""

from __future__ import annotations

import dataclasses
import io
import tempfile
import wave
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from tests.api.conftest import Api
from tests.api.test_audio import MIC, RATE, database, recorded  # noqa: F401 - fixtures
from tests.api.test_session_delete import RecordingSearch
from vozata.api.routes import bundle as bundle_routes
from vozata.storage import bundle_import
from vozata.storage.sqlite.bundle_import import SqliteBundleImporter


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


@pytest.fixture
def importing(api: Api, recorded: str) -> str:  # noqa: F811
    """`recorded` with a SQLite bundle importer and the manager on the same repository."""
    container = api.app.state.container
    importer = SqliteBundleImporter(
        container.store, container.audio, RATE, free_space=lambda _path: 1 << 40
    )
    api.app.state.container = dataclasses.replace(
        container, bundle_importer=importer, search_index=None
    )
    api.manager._store = container.store
    return recorded


def _post(api: Api, body: bytes) -> httpx.Response:
    return api.client.post(
        "/sessions/import", content=body, headers={"Content-Type": "application/zip"}
    )


def test_a_bundle_brings_back_the_audio_of_the_same_meeting(api: Api, importing: str) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content
    assert api.client.delete(f"/sessions/{importing}/audio").status_code == 204

    response = _post(api, bundle)

    assert response.status_code == 200
    assert response.json() == {"id": importing, "mode": "audio_restored"}
    assert api.client.get(f"/sessions/{importing}").json()["audio"]["mic"] == 2.5


def test_a_bundle_of_a_deleted_meeting_imports_it_again(api: Api, importing: str) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content
    assert api.client.delete(f"/sessions/{importing}").status_code == 204

    response = _post(api, bundle)

    assert response.json() == {"id": importing, "mode": "imported"}
    assert api.client.get(f"/sessions/{importing}").json()["status"] == "done"


def test_a_meeting_that_still_has_its_audio_is_409(api: Api, importing: str) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content

    response = _post(api, bundle)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_exists"


def test_a_file_that_is_not_a_bundle_is_422(api: Api, importing: str) -> None:
    response = _post(api, b"not a zip")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "bundle_invalid"


def test_a_bundle_larger_than_the_limit_is_413(
    api: Api,
    importing: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content
    monkeypatch.setattr(bundle_import, "MAX_BUNDLE_BYTES", len(bundle) - 1)

    response = _post(api, bundle)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "bundle_too_large"


def test_a_bundle_that_unpacks_to_more_than_the_limit_is_413(
    api: Api, importing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = io.BytesIO()
    with ZipFile(body, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{importing}/session.json", b" " * 100_000)  # deflates to ~100 bytes
    monkeypatch.setattr(bundle_import, "MAX_BUNDLE_BYTES", 50_000)

    response = _post(api, body.getvalue())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "bundle_too_large"


def test_a_short_disk_is_507(api: Api, importing: str) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content
    api.client.delete(f"/sessions/{importing}")
    container = api.app.state.container
    short = SqliteBundleImporter(container.store, container.audio, RATE, lambda _path: 0)
    api.app.state.container = dataclasses.replace(container, bundle_importer=short)

    response = _post(api, bundle)

    assert response.status_code == 507
    assert response.json()["error"]["code"] == "not_enough_space"


def test_the_file_backend_index_gets_the_imported_transcript(api: Api, importing: str) -> None:
    bundle = api.client.get(f"/sessions/{importing}/bundle").content
    api.client.delete(f"/sessions/{importing}")
    search = RecordingSearch()
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=search)

    assert _post(api, bundle).status_code == 200

    assert [session_id for session_id, _ in search.indexed] == [importing]


def test_without_an_importer_the_import_is_503(api: Api) -> None:
    response = _post(api, b"PK")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "import_unavailable"


def test_a_streamed_bundle_is_cut_off_at_the_limit(
    api: Api, importing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bundle_import, "MAX_BUNDLE_BYTES", 10)

    response = api.client.post("/sessions/import", content=iter([b"PK" * 4, b"PK" * 4]))

    assert response.status_code == 413


def test_a_failed_export_leaves_no_temporary_folder(
    api: Api,
    recorded: str,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(bundle_routes, "write_folder", fail)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()

    assert api.client.get(f"/sessions/{recorded}/bundle").status_code == 500

    assert list((tmp_path / "temp").iterdir()) == []
