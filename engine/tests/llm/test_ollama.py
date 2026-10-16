from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from vozata.llm.ollama import OllamaLanguageModel
from vozata.ports import LanguageModel, LanguageModelError

URL = "http://ollama.test:11434"


def model_with(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaLanguageModel:
    return OllamaLanguageModel(URL, "qwen2.5:7b", transport=httpx.MockTransport(handler))


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"role": "assistant", "content": content}, "done": True}
    )


def test_satisfies_the_language_model_port() -> None:
    assert isinstance(model_with(lambda request: chat_reply("")), LanguageModel)


def test_generate_posts_a_non_streaming_chat_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return chat_reply("## Summary\n...")

    reply = model_with(handler).generate("be precise", "transcript")

    assert reply == "## Summary\n..."
    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{URL}/api/chat")
    assert json.loads(request.content) == {
        "model": "qwen2.5:7b",
        "messages": [
            {"role": "system", "content": "be precise"},
            {"role": "user", "content": "transcript"},
        ],
        "stream": False,
        "options": {"num_ctx": 8192},
    }


def test_generate_sends_the_json_schema_as_format() -> None:
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return chat_reply("{}")

    model_with(handler).generate("s", "p", json_schema=schema)

    assert bodies[0]["format"] == schema


def test_stream_yields_text_from_ndjson_lines_until_done() -> None:
    lines = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": ""}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True},
        {"message": {"content": "ignored"}, "done": False},
    ]
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        text = "\n".join(json.dumps(line) for line in lines) + "\n\n"
        return httpx.Response(200, content=text.encode())

    assert list(model_with(handler).stream("s", "p")) == ["Hel", "lo"]
    assert bodies[0]["stream"] is True


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, json={"error": "model crashed"}),
        lambda request: httpx.Response(404, json={"error": "model not found"}),
        lambda request: httpx.Response(200, content=b"not json"),
        lambda request: httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_generate_failures_raise_language_model_error(
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    with pytest.raises(LanguageModelError):
        model_with(handler).generate("s", "p")


def test_timeouts_and_connection_errors_raise_language_model_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LanguageModelError):
        model_with(timeout).generate("s", "p")
    with pytest.raises(LanguageModelError):
        list(model_with(refused).stream("s", "p"))


def test_stream_error_line_raises_language_model_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"error": "out of memory"}\n')

    with pytest.raises(LanguageModelError, match="out of memory"):
        list(model_with(handler).stream("s", "p"))


@pytest.mark.parametrize(
    ("names", "available"),
    [
        (["qwen2.5:7b", "llama3:8b"], True),
        (["qwen2.5:3b"], False),
        ([], False),
    ],
)
def test_is_available_checks_that_the_model_is_pulled(names: list[str], available: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("GET", "/api/tags")
        return httpx.Response(200, json={"models": [{"name": name} for name in names]})

    assert model_with(handler).is_available() is available


def test_untagged_model_name_matches_latest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "mistral:latest"}]})

    transport = httpx.MockTransport(handler)
    assert OllamaLanguageModel(URL, "mistral", transport=transport).is_available()


def test_is_available_is_false_when_the_server_is_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert model_with(handler).is_available() is False


def test_close_closes_the_http_client() -> None:
    model = model_with(lambda request: chat_reply("x"))

    model.close()

    with pytest.raises(LanguageModelError):
        model.generate("s", "p")


def test_stream_skips_blank_lines_and_ends_when_the_body_ends() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = '{"message": {"content": "a"}}\n\n   \n{"message": {"content": "b"}}\n'
        return httpx.Response(200, content=body.encode())

    assert list(model_with(handler).stream("s", "p")) == ["a", "b"]
