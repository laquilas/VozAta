from __future__ import annotations

from collections.abc import Callable
from urllib.parse import unquote

import httpx
import numpy as np
import pytest

from vozata.config import ConfigError
from vozata.domain import TranscriptionResult, Word
from vozata.ports import WorkerUnreachableError
from vozata.transcription.retry import TranscriptionRequestError
from vozata.worker_client.client import WorkerClient

URL = "http://192.168.68.101:8766"
REPLY = {
    "words": [{"text": " Olá", "start": 0.0, "end": 0.4, "probability": 0.8}],
    "language": "pt",
    "avg_logprob": -0.2,
}
SPEECH = np.full(1600, 0.1, dtype=np.float32)

Handler = Callable[[httpx.Request], httpx.Response]


def _health(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/health":
        return httpx.Response(200, json={"worker": "ok"})
    return None


def _serving(reply: dict = REPLY, seen: list[httpx.Request] | None = None) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return _health(request) or httpx.Response(200, json=reply)

    return handle


def _client(handler: Handler, token: str | None = "t0k") -> WorkerClient:
    return WorkerClient(URL, token, transport=httpx.MockTransport(handler), sleep=lambda _: None)


def test_requests_carry_the_bearer_token() -> None:
    seen: list[httpx.Request] = []

    _client(_serving(seen=seen)).transcribe(SPEECH, "pt", None, None)

    assert [r.headers["authorization"] for r in seen] == ["Bearer t0k", "Bearer t0k"]


def test_without_a_token_no_authorization_is_sent() -> None:
    seen: list[httpx.Request] = []

    _client(_serving(seen=seen), token=None).transcribe(SPEECH, None, None, None)

    assert all("authorization" not in r.headers for r in seen)


def test_the_request_carries_samples_language_hints_and_prompt() -> None:
    seen: list[httpx.Request] = []

    result = _client(_serving(seen=seen)).transcribe(SPEECH, "pt", "VozAta, Ação", "olá, tudo")

    request = seen[-1]
    assert (request.method, request.url.path, request.url.params["language"]) == (
        "POST",
        "/transcribe",
        "pt",
    )
    np.testing.assert_array_equal(np.frombuffer(request.content, dtype="<f4"), SPEECH)
    assert unquote(request.headers["x-hints"]) == "VozAta, Ação"
    assert unquote(request.headers["x-prompt"]) == "olá, tudo"
    assert result == TranscriptionResult((Word(" Olá", 0.0, 0.4, 0.8),), "pt", -0.2)


def test_missing_language_hints_and_prompt_are_left_out() -> None:
    seen: list[httpx.Request] = []

    _client(_serving(seen=seen)).transcribe(SPEECH, None, " ", None)

    request = seen[-1]
    assert request.url.params.get("language", "") == ""
    assert "x-hints" not in request.headers and "x-prompt" not in request.headers


def test_the_worker_is_probed_once() -> None:
    seen: list[httpx.Request] = []
    client = _client(_serving(seen=seen))

    client.transcribe(SPEECH, None, None, None)
    client.transcribe(SPEECH, None, None, None)

    assert [r.url.path for r in seen] == ["/health", "/transcribe", "/transcribe"]


def test_silence_is_not_sent() -> None:
    seen: list[httpx.Request] = []

    result = _client(_serving(seen=seen)).transcribe(
        np.zeros(1600, dtype=np.float32), "pt", None, None
    )

    assert (result, seen) == (TranscriptionResult((), "pt"), [])


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("t"), httpx.ReadTimeout("t")]
)
def test_a_worker_that_does_not_answer_the_probe_is_unreachable(error: Exception) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(WorkerUnreachableError) as caught:
        _client(handle).probe()

    assert caught.value.host == "192.168.68.101"


def test_a_refused_token_is_a_setup_error() -> None:
    client = _client(lambda request: httpx.Response(401, json={"error": {}}))

    with pytest.raises(ConfigError) as caught:
        client.transcribe(SPEECH, None, None, None)

    assert (caught.value.key, caught.value.message_key) == ("WORKER_TOKEN", "worker_unauthorized")
    assert caught.value.value == "********"  # the token is never shown
    assert caught.value.params == {"host": "192.168.68.101"}


def test_a_token_refused_after_the_probe_is_a_setup_error_too() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return _health(request) or httpx.Response(401)

    with pytest.raises(ConfigError):
        _client(handle).transcribe(SPEECH, None, None, None)


def test_a_busy_worker_is_retried() -> None:
    answers = iter([httpx.Response(503), httpx.Response(200, json=REPLY)])

    def handle(request: httpx.Request) -> httpx.Response:
        return _health(request) or next(answers)

    result = _client(handle).transcribe(SPEECH, None, None, None)

    assert result.language == "pt"


def test_losing_the_worker_mid_session_is_unreachable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if _health(request):
            return httpx.Response(200)
        raise httpx.ConnectError("refused")

    with pytest.raises(WorkerUnreachableError):
        _client(handle).transcribe(SPEECH, None, None, None)


def test_a_failing_worker_is_a_request_error_not_unreachable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return _health(request) or httpx.Response(500)

    with pytest.raises(TranscriptionRequestError):
        _client(handle).transcribe(SPEECH, None, None, None)


def test_a_refused_body_is_a_request_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return _health(request) or httpx.Response(422, json={"error": {"code": "x"}})

    with pytest.raises(TranscriptionRequestError, match="422"):
        _client(handle).transcribe(SPEECH, None, None, None)


def test_the_host_of_an_ipv6_address() -> None:
    assert WorkerClient("http://[::1]:8766", None).host == "::1"


def test_close_closes_the_connection() -> None:
    seen: list[httpx.Request] = []
    client = _client(_serving(seen=seen))

    client.close()

    with pytest.raises(RuntimeError):
        client.transcribe(SPEECH, None, None, None)
    assert seen == []
