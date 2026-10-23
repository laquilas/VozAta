"""The engine's translator over the worker (phase 46)."""

from __future__ import annotations

import json

import httpx
import pytest

from vozata.ports import TranslationError
from vozata.worker_client.client import WorkerClient
from vozata.worker_client.translator import WorkerTranslator

URL = "http://gpu-pc:8766"


class _Notices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fallback(self, task: str, host: str) -> None:
        self.calls.append((task, host))


class _Local:
    def __init__(self) -> None:
        self.closed = False

    def translate(self, text: str, source: str, target: str) -> str:
        return f"local:{text}"

    def close(self) -> None:
        self.closed = True


class _Worker:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.off = False
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={})
        if self.off:
            raise httpx.ConnectError("refused")
        self.bodies.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(
                self.status, json={"error": {"code": "worker_translation_failed"}}
            )
        return httpx.Response(200, json={"text": "hello"})


def _client(worker: _Worker) -> WorkerClient:
    return WorkerClient(URL, "t", transport=httpx.MockTransport(worker))


def test_segments_are_translated_on_the_worker_then_here_when_it_is_lost() -> None:
    worker = _Worker()
    notices = _Notices()
    built: list[_Local] = []

    def local() -> _Local:
        built.append(_Local())
        return built[-1]

    translator = WorkerTranslator(_client(worker), local, notices)

    first = translator.translate("olá", "pt", "en")
    worker.off = True
    second = translator.translate("tchau", "pt", "en")
    third = translator.translate("oi", "pt", "en")
    translator.close()

    assert (first, second, third) == ("hello", "local:tchau", "local:oi")
    assert worker.bodies == [{"text": "olá", "source": "pt", "target": "en"}]
    assert notices.calls == [("translation", "gpu-pc")]
    assert len(built) == 1 and built[0].closed


def test_a_worker_error_is_a_translation_error() -> None:
    worker = _Worker()
    worker.status = 422

    with pytest.raises(TranslationError, match="worker_translation_failed"):
        WorkerTranslator(_client(worker), _Local, _Notices()).translate("x", "pt", "en")
