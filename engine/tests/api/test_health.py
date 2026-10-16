from __future__ import annotations

from pathlib import Path

from tests.api.conftest import Api
from vozata.api.system_info import GpuInfo


def test_health_reports_engine_gpu_stt_and_llm(api: Api) -> None:
    response = api.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "engine": "ok",
        "version": "0.1.0",
        "gpu": {"available": True, "name": "RTX 3050", "vram_total_mb": 6144},
        "stt": {"provider": "faster_whisper", "model": "large-v3-turbo", "device": "auto"},
        "llm": {"provider": "ollama", "model": "qwen2.5:7b", "reachable": True},
    }


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
