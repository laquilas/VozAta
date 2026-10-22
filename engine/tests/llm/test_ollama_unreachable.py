"""Phase 43: an Ollama server that does not answer fails fast with `LlmUnreachableError`."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from vozata.llm.ollama import OllamaLanguageModel
from vozata.ports import LanguageModelError, LlmUnreachableError

URL = "http://192.168.0.20:11434"


class Server:
    """A scripted Ollama: what `/api/tags` and `/api/chat` do, and the requests it saw."""

    def __init__(
        self,
        tags: Callable[[], httpx.Response] | Exception | None = None,
        chat: Callable[[], httpx.Response] | Exception | None = None,
    ) -> None:
        self.tags = tags or (lambda: httpx.Response(200, json={"models": []}))
        self.chat = chat or (
            lambda: httpx.Response(200, json={"message": {"content": "ok"}, "done": True})
        )
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        answer = self.tags if request.url.path == "/api/tags" else self.chat
        if isinstance(answer, Exception):
            raise answer
        return answer()

    def model(self) -> OllamaLanguageModel:
        return OllamaLanguageModel(URL, "qwen2.5:7b", transport=httpx.MockTransport(self))


def _request() -> httpx.Request:
    return httpx.Request("GET", URL)


OFF_PC = [
    httpx.ConnectError("refused", request=_request()),
    httpx.ConnectTimeout("no route", request=_request()),
    httpx.ReadTimeout("silent", request=_request()),
]


@pytest.mark.parametrize("failure", OFF_PC, ids=lambda e: type(e).__name__)
def test_generate_raises_unreachable_when_the_probe_cannot_connect(failure: Exception) -> None:
    server = Server(tags=failure)

    with pytest.raises(LlmUnreachableError) as caught:
        server.model().generate("system", "prompt")

    assert caught.value.host == "192.168.0.20"
    assert "/api/chat" not in server.paths


@pytest.mark.parametrize("failure", OFF_PC, ids=lambda e: type(e).__name__)
def test_stream_raises_unreachable_when_the_probe_cannot_connect(failure: Exception) -> None:
    server = Server(tags=failure)

    with pytest.raises(LlmUnreachableError) as caught:
        list(server.model().stream("system", "prompt"))

    assert caught.value.host == "192.168.0.20"
    assert "/api/chat" not in server.paths


def test_the_unreachable_error_is_a_language_model_error_naming_the_host() -> None:
    error = LlmUnreachableError("gpu-box", "refused")

    assert isinstance(error, LanguageModelError)
    assert "gpu-box" in str(error) and "refused" in str(error)


def test_the_probe_runs_once_per_model() -> None:
    server = Server()
    model = server.model()

    model.generate("s", "p")
    model.generate("s", "p")

    assert server.paths.count("/api/tags") == 1
    assert server.paths.count("/api/chat") == 2


def test_a_failed_probe_is_remembered_without_asking_the_server_again() -> None:
    server = Server(tags=OFF_PC[0])
    model = server.model()

    for _ in range(2):
        with pytest.raises(LlmUnreachableError):
            model.generate("s", "p")

    assert server.paths == ["/api/tags"]


def test_a_probe_http_error_is_not_unreachable() -> None:
    server = Server(tags=lambda: httpx.Response(500))

    assert server.model().generate("s", "p") == "ok"


def test_the_server_going_away_during_the_job_is_unreachable() -> None:
    server = Server(chat=httpx.ConnectError("gone", request=_request()))

    with pytest.raises(LlmUnreachableError) as caught:
        server.model().generate("s", "p")

    assert caught.value.host == "192.168.0.20"


def test_a_chat_read_timeout_is_still_a_plain_failure() -> None:
    server = Server(chat=httpx.ReadTimeout("slow model", request=_request()))

    with pytest.raises(LanguageModelError) as caught:
        server.model().generate("s", "p")

    assert not isinstance(caught.value, LlmUnreachableError)


def test_stream_connect_error_is_unreachable() -> None:
    server = Server(chat=httpx.ConnectError("gone", request=_request()))

    with pytest.raises(LlmUnreachableError):
        list(server.model().stream("s", "p"))


def test_release_after_an_unreachable_probe_sends_nothing() -> None:
    server = Server(tags=OFF_PC[1])
    model = server.model()
    with pytest.raises(LlmUnreachableError):
        model.generate("s", "p")

    model.release()

    assert server.paths == ["/api/tags"]  # a dead host must not hold the queue for 300 s


def test_release_after_a_good_probe_still_unloads() -> None:
    server = Server()
    model = server.model()
    model.generate("s", "p")

    model.release()

    assert server.paths == ["/api/tags", "/api/chat", "/api/chat"]
