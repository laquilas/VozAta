"""The worker's HTTP API (phase 44, `docs/roadmap/worker-api.md`)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI

from vozata import __version__
from vozata.api.system_info import GpuInfo
from vozata.worker.auth import Unauthorized, token_guard, unauthorized

CAPABILITIES = ["speech"]


def create_worker_app(
    token: str | None,
    *,
    gpu_info: Callable[[], GpuInfo],
    models: Callable[[], list[str]],
) -> FastAPI:
    """Every route needs `token` (None: no check, for a worker on loopback)."""
    app = FastAPI(
        title="VozAta worker",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(token_guard(token))],
    )
    app.add_exception_handler(Unauthorized, unauthorized)

    @app.get("/health")
    def health() -> dict[str, object]:
        gpu = gpu_info()
        return {
            "worker": "ok",
            "version": __version__,
            "gpu": {
                "available": gpu.available,
                "name": gpu.name,
                "vram_total_mb": gpu.vram_total_mb,
            },
            "capabilities": CAPABILITIES,
            "models": models(),
        }

    return app
