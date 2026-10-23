from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from tests.api.conftest import Api
from vozata.api.system_info import GpuInfo
from vozata.domain import StorageInfo
from vozata.storage.audio_cache import WavCache


def test_health_reports_engine_gpu_stt_and_llm(api: Api) -> None:
    response = api.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "engine": "ok",
        "version": "0.2.1",
        "gpu": {"available": True, "name": "RTX 3050", "vram_total_mb": 6144},
        "stt": {"provider": "faster_whisper", "model": "large-v3-turbo", "device": "auto"},
        "llm": {
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "reachable": True,
            "remote": False,
            "host": None,
        },
        "storage": {
            "backend": "files",
            "database": None,
            "warning": None,
            "size_bytes": None,
            "audio_cache_bytes": 0,
        },
        "worker": None,
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


def test_an_ollama_on_another_pc_is_reported_remote_with_its_host(tmp_path: Path) -> None:
    from vozata.config import Settings

    settings = Settings(output_dir=tmp_path / "recordings", ollama_url="http://192.168.0.20:11434")
    remote = Api(tmp_path, settings)
    with remote.client:
        llm = remote.client.get("/health").json()["llm"]

    assert (llm["remote"], llm["host"]) == (True, "192.168.0.20")


def test_health_goes_back_to_local_when_the_url_is_saved_as_localhost(tmp_path: Path) -> None:
    from vozata.config import Settings

    settings = Settings(output_dir=tmp_path / "recordings", ollama_url="http://192.168.0.20:11434")
    remote = Api(tmp_path, settings)
    with remote.client:
        saved = remote.client.put(
            "/settings", json={"values": {"OLLAMA_URL": "http://localhost:11434"}}
        )
        llm = remote.client.get("/health").json()["llm"]

    assert saved.status_code == 200
    assert (llm["remote"], llm["host"]) == (False, None)


def test_a_remote_url_does_not_matter_when_the_provider_is_not_ollama(tmp_path: Path) -> None:
    from vozata.config import Settings

    settings = Settings(
        output_dir=tmp_path / "recordings",
        llm_provider="fake",
        ollama_url="http://192.168.0.20:11434",
    )
    other = Api(tmp_path, settings)
    with other.client:
        llm = other.client.get("/health").json()["llm"]

    assert (llm["remote"], llm["host"]) == (False, None)


def test_without_a_worker_url_there_is_no_worker(api: Api) -> None:
    assert api.client.get("/health").json()["worker"] is None


def _with_worker(tmp_path: Path, status: object, **overrides: object) -> Api:
    from vozata.config import Settings

    settings = Settings(
        output_dir=tmp_path / "recordings",
        worker_url="http://192.168.0.30:8766",
        worker_token="t0k",
        **overrides,  # type: ignore[arg-type]
    )
    api = Api(tmp_path, settings)
    asked: list[object] = []
    api.app.state.container = dataclasses.replace(
        api.app.state.container,
        worker_status=lambda current: asked.append(current.worker_token) or status,
    )
    api.asked = asked  # type: ignore[attr-defined]
    return api


def test_health_reports_the_worker(tmp_path: Path) -> None:
    from vozata.worker_client.status import WorkerStatus

    api = _with_worker(tmp_path, WorkerStatus(True, "0.9.0", ["large-v3-turbo"]))
    with api.client:
        body = api.client.get("/health").json()

    assert body["worker"] == {
        "url": "http://192.168.0.30:8766",
        "reachable": True,
        "version": "0.9.0",
        "tasks": {"speech": "local", "speakers": "local", "translation": "local"},
    }
    assert body["stt"]["provider"] == "faster_whisper"  # the worker is set up but not used
    assert api.asked == ["t0k"]  # type: ignore[attr-defined]


def test_speech_on_the_worker_is_named_by_its_host_and_model(tmp_path: Path) -> None:
    from vozata.worker_client.status import WorkerStatus

    api = _with_worker(
        tmp_path, WorkerStatus(True, "0.9.0", ["large-v3-turbo"]), stt_provider="vozata_worker"
    )
    with api.client:
        stt = api.client.get("/health").json()["stt"]

    assert stt == {"provider": "vozata_worker", "model": "large-v3-turbo", "device": "192.168.0.30"}


def test_a_worker_that_is_off_is_reported_unreachable(tmp_path: Path) -> None:
    from vozata.worker_client.status import WorkerStatus

    api = _with_worker(tmp_path, WorkerStatus(False), stt_provider="vozata_worker")
    with api.client:
        body = api.client.get("/health").json()

    assert body["worker"]["reachable"] is False
    assert body["stt"]["model"] == ""
    assert body["worker"]["tasks"]["speech"] == "fallback"


@pytest.mark.parametrize(("reachable", "placed"), [(True, "worker"), (False, "fallback")])
def test_health_says_where_each_task_runs(tmp_path: Path, reachable: bool, placed: str) -> None:
    from vozata.worker_client.status import WorkerStatus

    api = _with_worker(
        tmp_path,
        WorkerStatus(reachable),
        stt_provider="vozata_worker",
        diarization_provider="vozata_worker",
        translation_provider="vozata_worker",
    )
    with api.client:
        tasks = api.client.get("/health").json()["worker"]["tasks"]

    assert tasks == {"speech": placed, "speakers": placed, "translation": placed}


def test_health_without_gpu_or_llm(api: Api) -> None:
    api.gpu = GpuInfo(False)
    api.reachable = False

    body = api.client.get("/health").json()

    assert body["gpu"] == {"available": False, "name": None, "vram_total_mb": None}
    assert body["llm"]["reachable"] is False
    assert body["engine"] == "ok"


def _with_cache(api: Api) -> WavCache:
    cache = WavCache(api.settings.output_dir / "cache", 1 << 30)
    api.app.state.container = dataclasses.replace(api.app.state.container, audio_cache=cache)
    return cache


def test_health_reports_the_database_and_audio_cache_sizes(api: Api, tmp_path: Path) -> None:
    database = tmp_path / "vozata.db"
    database.write_bytes(b"x" * 4096)
    (tmp_path / "vozata.db-wal").write_bytes(b"x" * 100)
    cache = api.settings.output_dir / "cache" / "20261016_090000"
    cache.mkdir(parents=True)
    (cache / "mixed.wav").write_bytes(b"x" * 2048)
    _with_cache(api)
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, storage=StorageInfo("sqlite", database)
    )

    storage = api.client.get("/health").json()["storage"]

    assert storage["size_bytes"] == 4196
    assert storage["audio_cache_bytes"] == 2048


def test_a_missing_database_counts_zero_bytes(api: Api, tmp_path: Path) -> None:
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, storage=StorageInfo("sqlite", tmp_path / "none.db")
    )
    _with_cache(api)

    storage = api.client.get("/health").json()["storage"]

    assert (storage["size_bytes"], storage["audio_cache_bytes"]) == (0, 0)


def test_clearing_the_audio_cache_frees_its_bytes(api: Api) -> None:
    _with_cache(api)
    cache = api.settings.output_dir / "cache"
    (cache / "a").mkdir(parents=True)
    (cache / "a" / "mic.wav").write_bytes(b"x" * 300)
    (cache / "b").mkdir()
    (cache / "b" / "mixed.wav").write_bytes(b"x" * 200)

    response = api.client.delete("/storage/cache")

    assert response.status_code == 200
    assert response.json() == {"freed_bytes": 500}
    assert cache.is_dir() and list(cache.iterdir()) == []
    assert api.client.get("/health").json()["storage"]["audio_cache_bytes"] == 0


def test_a_cached_file_in_use_is_kept_and_not_counted(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _with_cache(api)
    cache = api.settings.output_dir / "cache" / "a"
    cache.mkdir(parents=True)
    (cache / "mixed.wav").write_bytes(b"x" * 400)  # being played
    (cache / "mic.wav").write_bytes(b"x" * 100)
    unlink = Path.unlink

    def fake_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "mixed.wav":
            raise PermissionError("in use")
        unlink(self, missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)

    with caplog.at_level(logging.WARNING):
        response = api.client.delete("/storage/cache")

    assert response.json() == {"freed_bytes": 100}
    assert (cache / "mixed.wav").exists()
    assert "mixed.wav" in caplog.text


def test_without_a_cache_there_is_nothing_to_clear(api: Api) -> None:
    (api.settings.output_dir / "cache" / "a").mkdir(parents=True)  # not ours: files backend
    (api.settings.output_dir / "cache" / "a" / "mic.wav").write_bytes(b"x")

    assert api.client.delete("/storage/cache").json() == {"freed_bytes": 0}
    assert api.client.get("/health").json()["storage"]["audio_cache_bytes"] == 0


def test_clearing_a_missing_audio_cache_frees_nothing(api: Api) -> None:
    _with_cache(api)

    assert api.client.delete("/storage/cache").json() == {"freed_bytes": 0}
