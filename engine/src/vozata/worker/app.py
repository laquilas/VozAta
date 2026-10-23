"""The worker's HTTP API (phases 44, 47, `docs/roadmap/worker-api.md`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from urllib.parse import unquote

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from vozata import __version__
from vozata.api.system_info import GpuInfo
from vozata.worker.auth import Unauthorized, token_guard, unauthorized
from vozata.worker.local import WorkerIdentity, is_loopback_client
from vozata.worker.pairing import PairingCodes, PairResult
from vozata.worker.speech import SpeechService

CAPABILITIES = ["speech"]
INVALID_AUDIO = "worker_invalid_audio"
FLOAT32_BYTES = 4
_PAIR_ERRORS = {
    PairResult.REFUSED: (403, "worker_pairing_refused"),
    PairResult.LOCKED: (423, "worker_pairing_locked"),
}


class PairRequest(BaseModel):
    code: str


def create_worker_app(
    token: str | None,
    *,
    gpu_info: Callable[[], GpuInfo],
    speech: SpeechService,
    identity: WorkerIdentity | None = None,
    pairing: PairingCodes | None = None,
    addresses: Callable[[], list[str]] = list,
) -> FastAPI:
    """`/health` and `/transcribe` need `token` (None: no check, for a worker on loopback);
    `/pair` needs the pairing code instead, and `/local/status` answers this PC only."""
    identity = identity or WorkerIdentity(None, "worker", 8766)
    pairing = pairing or PairingCodes()

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
        lifespan=lifespan,
    )
    app.add_exception_handler(Unauthorized, unauthorized)
    guarded = APIRouter(dependencies=[Depends(token_guard(token))])

    def gpu() -> dict[str, object]:
        info = gpu_info()
        return {"available": info.available, "name": info.name, "vram_total_mb": info.vram_total_mb}

    @guarded.get("/health")
    def health() -> dict[str, object]:
        return {
            "worker": "ok",
            "version": __version__,
            "gpu": gpu(),
            "capabilities": CAPABILITIES,
            "models": speech.models(),
        }

    @guarded.post("/transcribe")
    async def transcribe(request: Request, language: str = "") -> JSONResponse:
        """Body: float32 little-endian mono samples at 16 kHz."""
        body = await request.body()
        if not body or len(body) % FLOAT32_BYTES:
            return _error(422, INVALID_AUDIO)
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

    @app.post("/pair")
    def pair(body: PairRequest) -> JSONResponse:
        """The code shown on the worker PC buys the token (phase 47)."""
        if token is None:
            return _error(409, "worker_no_token")
        result = pairing.check(body.code)
        if result is not PairResult.OK:
            return _error(*_PAIR_ERRORS[result])
        return JSONResponse({"token": token, "id": identity.id, "name": identity.name})

    @app.get("/local/status")
    def local_status(request: Request) -> JSONResponse:
        """For the worker app on this PC only: it shows the token and the pairing code."""
        if not is_loopback_client(request.client.host if request.client else None):
            return _error(403, "worker_local_only")
        code, expires_in = pairing.current()
        return JSONResponse(
            {
                "version": __version__,
                "id": identity.id,
                "name": identity.name,
                "port": identity.port,
                "addresses": addresses(),
                "token": token,
                "pairing_code": code if token else None,
                "code_expires_in": round(expires_in) if token else None,
                "gpu": gpu(),
                "models": speech.models(),
            }
        )

    app.include_router(guarded)
    return app


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


def _header(request: Request, name: str) -> str | None:
    """A percent-encoded UTF-8 header (HTTP headers are Latin-1); empty means none."""
    return unquote(request.headers.get(name, "")) or None
