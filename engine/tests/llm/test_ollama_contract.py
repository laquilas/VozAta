from __future__ import annotations

import json

import httpx
import pytest

from tests.llm.contract import *  # noqa: F403
from tests.llm.contract import Harness
from vozata.llm.ollama import OllamaLanguageModel

URL = "http://ollama.test:11434"


def _model(handler: httpx.MockTransport) -> OllamaLanguageModel:
    return OllamaLanguageModel(URL, "qwen2.5:7b", transport=handler)


def _replying(text: str) -> OllamaLanguageModel:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
        body = json.loads(request.content)
        if not body.get("messages"):  # release
            return httpx.Response(200, json={"done": True})
        if body.get("stream"):
            words = text.split(" ")
            lines = [
                json.dumps({"message": {"content": word + (" " if i < len(words) - 1 else "")}})
                for i, word in enumerate(words)
            ]
            lines.append(json.dumps({"done": True}))
            return httpx.Response(200, text="\n".join(lines))
        return httpx.Response(200, json={"message": {"content": text}, "done": True})

    return _model(httpx.MockTransport(handler))


def _unreachable() -> OllamaLanguageModel:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return _model(httpx.MockTransport(handler))


def _failing() -> OllamaLanguageModel:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(500, json={"error": "out of memory"})

    return _model(httpx.MockTransport(handler))


@pytest.fixture
def harness() -> Harness:
    return Harness(_replying, _unreachable, _failing)
