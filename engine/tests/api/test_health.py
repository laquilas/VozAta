from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.api.conftest import Api
from vozata.api.system_info import GpuInfo
from vozata.domain import StorageInfo


def test_health_reports_engine_gpu_stt_and_llm(api: Api) -> None:
    response = api.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "engine": "ok",
        "version": "0.1.0",
        "gpu": {"available": True, "name": "RTX 3050", "vram_total_mb": 6144},
        "stt": {"provider": "faster_whisper", "model": "large-v3-turbo", "device": "auto"},
        "llm": {"provider": "ollama", "model": "qwen2.5:7b", "reachable": True},
        "storage": {"backend": "files", "database": None, "warning": None},
    }


def test_health_reports_the_database_and_warns_when_it_is_in_onedrive(
    api: Api, tmp_path: Path
) -> None:
    database = tmp_path / "OneDrive" / "rec" / "vozata.db"
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, storage=StorageInfo("sqlite", database, tmp_path / "OneDrive")
    )

    storage = api.client.get("/health").json()["storage"]

    assert (storage["backend"], storage["database"]) == ("sqlite", str(database.resolve()))
    assert str(database.resolve()) in storage["warning"]  # localized (English here)
    assert str(tmp_path / "OneDrive") in storage["warning"]
    assert "DATABASE_PATH" in storage["warning"]


def test_health_has_no_warning_for_a_local_database(api: Api, tmp_path: Path) -> None:
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, storage=StorageInfo("sqlite", tmp_path / "vozata.db")
    )

    storage = api.client.get("/health").json()["storage"]

    assert storage["warning"] is None
    assert storage["database"] == str((tmp_path / "vozata.db").resolve())


def test_a_remote_speech_api_is_named_by_its_host(tmp_path: Path) -> None:
    from vozata.config import Settings

    settings = Settings(
        output_dir=tmp_path / "recordings",
        stt_provider="openai_compatible",
        openai_stt_url="https://api.groq.com/openai/v1",
        openai_stt_model="whisper-large-v3",
    )
    remote = Api(tmp_path, settings)
    with remote.client:
        stt = remote.client.get("/health").json()["stt"]

    assert stt == {
        "provider": "openai_compatible",
        "model": "whisper-large-v3",
        "device": "api.groq.com",
    }


def test_health_without_gpu_or_llm(api: Api) -> None:
    api.gpu = GpuInfo(False)
    api.reachable = False

    body = api.client.get("/health").json()

    assert body["gpu"] == {"available": False, "name": None, "vram_total_mb": None}
    assert body["llm"]["reachable"] is False
    assert body["engine"] == "ok"
