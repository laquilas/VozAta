from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from tests.llm.contract import *  # noqa: F403
from tests.llm.contract import Harness
from vozata.llm.openai_compatible import OpenAICompatibleLanguageModel
from vozata.ports import LanguageModelError

URL = "http://lmstudio.test:1234/v1"
Handler = Callable[[httpx.Request], httpx.Response]


def _models(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": [{"id": n} for n in names]})


def _chat(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]}
    )


def _sse(*events: str) -> httpx.Response:
    body = "".join(f"data: {event}\n\n" for event in events)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _delta(text: str) -> str:
    return json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]})


def _model(
    handler: Handler, model: str = "qwen2.5-7b-instruct", key: str | None = None
) -> OpenAICompatibleLanguageModel:
    def routed(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/models":
            return _models("qwen2.5-7b-instruct", "text-embedding")
        return handler(request)

    return OpenAICompatibleLanguageModel(URL, model, key, transport=httpx.MockTransport(routed))


def _replying(text: str) -> OpenAICompatibleLanguageModel:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("stream"):
            words = text.split(" ")
            pieces = [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]
            return _sse(*[_delta(piece) for piece in pieces], "[DONE]")
        return _chat(text)

    return _model(handler)


def _unreachable() -> OpenAICompatibleLanguageModel:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return OpenAICompatibleLanguageModel(URL, "m", transport=httpx.MockTransport(handler))


def _failing() -> OpenAICompatibleLanguageModel:
    return _model(lambda _: httpx.Response(500, json={"error": {"message": "model crashed"}}))


@pytest.fixture
def harness() -> Harness:
    return Harness(_replying, _unreachable, _failing)


def test_generate_posts_a_chat_completion_with_the_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _chat("minutes")

    reply = _model(handler, key="sk-x").generate("be precise", "transcript")

    assert reply == "minutes"
    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{URL}/chat/completions")
    assert request.headers["authorization"] == "Bearer sk-x"
    assert json.loads(request.content) == {
        "model": "qwen2.5-7b-instruct",
        "messages": [
            {"role": "system", "content": "be precise"},
            {"role": "user", "content": "transcript"},
        ],
        "stream": False,
    }


def test_without_a_key_no_authorization_is_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat("x")

    _model(handler).generate("s", "p")

    assert "authorization" not in seen[0].headers


def test_the_json_schema_goes_as_the_response_format() -> None:
    bodies: list[dict[str, object]] = []
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _chat('{"items": []}')

    _model(handler).generate("s", "p", json_schema=schema)

    assert bodies[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "reply", "schema": schema},
    }


def test_without_a_model_the_first_one_the_server_lists_is_used() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _chat("x")

    _model(handler, model="").generate("s", "p")

    assert bodies[0]["model"] == "qwen2.5-7b-instruct"


def test_a_server_without_models_and_no_model_set_fails_clearly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _models()
        return _chat("x")

    model = OpenAICompatibleLanguageModel(URL, "", transport=httpx.MockTransport(handler))

    with pytest.raises(LanguageModelError, match="OPENAI_LLM_MODEL"):
        model.generate("s", "p")


@pytest.mark.parametrize(
    ("configured", "available"),
    [("qwen2.5-7b-instruct", True), ("llama-3", False), ("", True)],
)
def test_is_available_checks_the_model_is_served(configured: str, available: bool) -> None:
    assert _model(lambda _: _chat(""), model=configured).is_available() is available


def test_is_available_is_false_on_an_http_error() -> None:
    model = OpenAICompatibleLanguageModel(
        URL, "m", transport=httpx.MockTransport(lambda _: httpx.Response(401))
    )

    assert model.is_available() is False


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, text="not json"),
    ],
)
def test_a_malformed_reply_is_a_language_model_error(reply: httpx.Response) -> None:
    with pytest.raises(LanguageModelError):
        _model(lambda _: reply).generate("s", "p")


def test_the_stream_skips_comments_and_empty_deltas_and_ends_with_the_body() -> None:
    events = [
        ": keep-alive",  # an SSE comment line, written raw below
    ]
    body = (
        f"{events[0]}\n\n"
        f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant'}}]})}\n\n"
        f"data: {_delta('Hello')}\n\n"
        f"data: {_delta(' world')}\n\n"
    )
    model = _model(lambda _: httpx.Response(200, text=body))

    assert list(model.stream("s", "p")) == ["Hello", " world"]


def test_an_error_event_in_the_stream_is_a_language_model_error() -> None:
    model = _model(lambda _: _sse(json.dumps({"error": {"message": "context too long"}})))

    with pytest.raises(LanguageModelError, match="context too long"):
        list(model.stream("s", "p"))


def test_the_probe_runs_once() -> None:
    probes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            probes.append("models")
            return _models("m")
        return _chat("x")

    model = OpenAICompatibleLanguageModel(URL, "m", transport=httpx.MockTransport(handler))
    model.generate("s", "p")
    model.generate("s", "p")

    assert probes == ["models"]


def test_a_probe_http_error_leaves_the_chat_request_to_report() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(404)
        return _chat("still fine")

    model = OpenAICompatibleLanguageModel(URL, "m", transport=httpx.MockTransport(handler))

    assert model.generate("s", "p") == "still fine"
