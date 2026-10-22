"""The worker's HTTP API (phase 44, `docs/roadmap/worker-api.md`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from urllib.parse import unquote

import numpy as np
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from vozata import __version__
from vozata.api.system_info import GpuInfo
from vozata.worker.auth import Unauthorized, token_guard, unauthorized
from vozata.worker.speech import SpeechService

CAPABILITIES = ["speech"]
INVALID_AUDIO = "worker_invalid_audio"
FLOAT32_BYTES = 4


def create_worker_app(
    token: str | None,
    *,
    gpu_info: Callable[[], GpuInfo],
    speech: SpeechService,
) -> FastAPI:
    """Every route needs `token` (None: no check, for a worker on loopback)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        speech.close()  # frees the GPU when the worker stops

    app = FastAPI(
        title="VozAta worker",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(token_guard(token))],
        lifespan=lifespan,
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
            "models": speech.models(),
        }

    @app.post("/transcribe")
    async def transcribe(request: Request, language: str = "") -> JSONResponse:
        """Body: float32 little-endian mono samples at 16 kHz."""
        body = await request.body()
        if not body or len(body) % FLOAT32_BYTES:
            return JSONResponse({"error": {"code": INVALID_AUDIO}}, status_code=422)
        samples = np.frombuffer(body, dtype="<f4").astype(np.float32)
        result = await run_in_threadpool(
            speech.transcribe,
            samples,
            language or None,
            _header(request, "x-hints"),
            _header(request, "x-prompt"),
        )
        return JSONResponse(
            {
                "words": [word.to_dict() for word in result.words],
                "language": result.language,
                "avg_logprob": result.avg_logprob,
            }
        )

    return app


def _header(request: Request, name: str) -> str | None:
    """A percent-encoded UTF-8 header (HTTP headers are Latin-1); empty means none."""
    return unquote(request.headers.get(name, "")) or None
