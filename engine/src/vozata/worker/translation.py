"""Live translation on the worker (phase 46): the opus-mt translator and `POST /translate`."""

from __future__ import annotations

import threading
from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from vozata.ports import TranslationError, Translator

UNAVAILABLE = "worker_translation_unavailable"


class TranslateService:
    """The translator, loaded on the first request and kept; one request at a time."""

    def __init__(self, factory: Callable[[], Translator]) -> None:
        self._factory = factory
        self._translator: Translator | None = None
        self._lock = threading.Lock()

    def translate(self, text: str, source: str, target: str) -> str:
        with self._lock:
            if self._translator is None:
                self._translator = self._factory()
            return self._translator.translate(text, source, target)

    def close(self) -> None:
        with self._lock:
            if self._translator is not None:
                self._translator.close()
                self._translator = None


class TranslateIn(BaseModel):
    text: str
    source: str
    target: str


def add_translation_route(router: APIRouter, service: TranslateService | None) -> None:
    """Without `service` (the `translation` extra is not installed there) the route answers 503."""

    @router.post("/translate")
    async def translate(body: TranslateIn) -> JSONResponse:
        if service is None:
            return _error(503, UNAVAILABLE)
        try:
            text = await run_in_threadpool(service.translate, body.text, body.source, body.target)
        except TranslationError as error:
            return JSONResponse(
                {"error": {"code": "worker_translation_failed", "message": str(error)}},
                status_code=422,
            )
        return JSONResponse({"text": text})


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)
