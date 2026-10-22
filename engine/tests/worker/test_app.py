from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vozata import __version__
from vozata.api.system_info import GpuInfo
from vozata.worker.app import create_worker_app

TOKEN = "s3cret-token"


def _client(token: str | None = TOKEN, models: list[str] | None = None) -> TestClient:
    app = create_worker_app(
        token,
        gpu_info=lambda: GpuInfo(True, "RTX 4070", 12282),
        models=lambda: list(models or []),
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic x"}],
)
def test_every_route_needs_the_token(headers: dict[str, str]) -> None:
    response = _client().get("/health", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "worker_unauthorized"


def test_health_answers_with_the_token() -> None:
    response = _client(models=["large-v3-turbo"]).get(
        "/health", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "worker": "ok",
        "version": __version__,
        "gpu": {"available": True, "name": "RTX 4070", "vram_total_mb": 12282},
        "capabilities": ["speech"],
        "models": ["large-v3-turbo"],
    }


def test_a_worker_on_loopback_without_a_token_answers_everyone() -> None:
    response = _client(token=None).get("/health")

    assert response.status_code == 200
