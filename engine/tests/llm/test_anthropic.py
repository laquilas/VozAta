from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from tests.llm.contract import *  # noqa: F403
from tests.llm.contract import Harness
from vozata.llm.anthropic import FALLBACK_BETA, AnthropicLanguageModel
from vozata.ports import LanguageModelError, LlmUnreachableError

API = "https://api.anthropic.com/v1/messages"


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx2.Request("POST", API))


def _status_error(status: int = 500) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=httpx2.Request("POST", API))
    return anthropic.APIStatusError("overloaded", response=response, body=None)


class _Stream:
    def __init__(self, pieces: list[str], stop_reason: str, owner: _Client) -> None:
        self._pieces = pieces
        self._stop = stop_reason
        self._owner = owner

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @property
    def text_stream(self) -> Iterator[str]:
        for piece in self._pieces:
            if self._owner.closed:
                raise _connection_error()
            yield piece

    def get_final_message(self) -> Any:
        block = SimpleNamespace(type="text", text="".join(self._pieces))
        details = SimpleNamespace(category="cyber", explanation="declined")
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), block],
            stop_reason=self._stop,
            stop_details=details if self._stop == "refusal" else None,
        )


class _Client:
    """The parts of `anthropic.Anthropic` the provider uses."""

    def __init__(
        self,
        pieces: list[str] | None = None,
        stop_reason: str = "end_turn",
        error: Exception | None = None,
    ) -> None:
        self.pieces = pieces or []
        self.stop_reason = stop_reason
        self.error = error
        self.requests: list[dict[str, Any]] = []
        self.retrieved: list[str] = []
        self.closed = False
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.models = SimpleNamespace(retrieve=self._retrieve)

    def _stream(self, **request: Any) -> _Stream:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return _Stream(self.pieces, self.stop_reason, self)

    def _retrieve(self, model: str) -> Any:
        self.retrieved.append(model)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(id=model)

    def close(self) -> None:
        self.closed = True


def _model(client: _Client, model: str = "claude-opus-5-5") -> AnthropicLanguageModel:
    return AnthropicLanguageModel("sk-ant-test", model, client_factory=lambda key: client)


def _replying(text: str) -> AnthropicLanguageModel:
    words = text.split(" ")
    return _model(_Client([w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]))


@pytest.fixture
def harness() -> Harness:
    return Harness(
        _replying,
        lambda: _model(_Client(error=_connection_error())),
        lambda: _model(_Client(error=_status_error())),
    )


def test_a_request_streams_with_effort_and_refusal_fallbacks() -> None:
    client = _Client(["minutes"])

    assert _model(client).generate("be precise", "transcript") == "minutes"

    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["system"] == "be precise"
    assert request["messages"] == [{"role": "user", "content": "transcript"}]
    assert request["max_tokens"] == 64000
    assert request["output_config"] == {"effort": "medium"}
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"
    assert "temperature" not in request and "thinking" not in request


def test_the_json_schema_is_sent_closed_as_the_output_format() -> None:
    client = _Client(['{"items": []}'])
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"owner": {"type": "string"}}},
            }
        },
        "required": ["items"],
    }

    _model(client).generate("s", "p", json_schema=schema)

    sent = client.requests[0]["output_config"]["format"]
    assert sent["type"] == "json_schema"
    assert sent["schema"]["additionalProperties"] is False
    assert sent["schema"]["properties"]["items"]["items"]["additionalProperties"] is False
    assert "additionalProperties" not in schema  # the caller's schema is left as it was


@pytest.mark.parametrize("call", ["generate", "stream"])
def test_a_refusal_is_a_language_model_error(call: str) -> None:
    model = _model(_Client(["Sorry"], stop_reason="refusal"))

    with pytest.raises(LanguageModelError, match="declined"):
        if call == "generate":
            model.generate("s", "p")
        else:
            list(model.stream("s", "p"))


def test_a_reply_cut_by_max_tokens_is_a_language_model_error() -> None:
    with pytest.raises(LanguageModelError, match="max_tokens"):
        _model(_Client(["half"], stop_reason="max_tokens")).generate("s", "p")


def test_a_timeout_is_a_plain_failure_not_unreachable() -> None:
    timeout = anthropic.APITimeoutError(request=httpx2.Request("POST", API))

    with pytest.raises(LanguageModelError) as raised:
        _model(_Client(error=timeout)).generate("s", "p")
    assert not isinstance(raised.value, LlmUnreachableError)


def test_an_unreachable_api_names_its_host() -> None:
    with pytest.raises(LlmUnreachableError) as raised:
        _model(_Client(error=_connection_error())).generate("s", "p")

    assert raised.value.host == "api.anthropic.com"


def test_is_available_retrieves_the_model() -> None:
    client = _Client()

    assert _model(client, "claude-sonnet-5-5").is_available() is True
    assert client.retrieved == ["claude-sonnet-5-5"]
    assert _model(_Client(error=_status_error(404))).is_available() is False


def test_without_a_key_nothing_is_sent_and_the_error_names_the_key() -> None:
    built: list[str] = []
    model = AnthropicLanguageModel(
        None, "claude-opus-5-5", client_factory=lambda key: built.append(key) or _Client()
    )

    with pytest.raises(LanguageModelError, match="ANTHROPIC_API_KEY"):
        model.generate("s", "p")
    assert model.is_available() is False
    assert built == []
    model.cancel()
    model.close()


def test_cancel_during_a_stream_stops_it() -> None:
    client = _Client(["a", "b", "c"])
    model = _model(client)
    stream = model.stream("s", "p")

    assert next(stream) == "a"
    model.cancel()

    with pytest.raises(LanguageModelError):
        list(stream)
    assert client.closed


def test_the_sdk_client_gets_the_key_and_a_bounded_retry() -> None:
    from vozata.llm.anthropic import sdk_client

    client = sdk_client("sk-ant-test")
    try:
        assert isinstance(client, anthropic.Anthropic)
        assert client.api_key == "sk-ant-test"
        assert client.max_retries == 2
    finally:
        client.close()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (None, 200),
        (_status_error(401), 401),
        (_status_error(404), 404),
        (_connection_error(), None),
    ],
)
def test_the_config_probe_reports_the_status_of_the_model_lookup(
    error: Exception | None, status: int | None
) -> None:
    from vozata.llm.anthropic import probe_status

    client = _Client(error=error)

    assert probe_status("sk-ant-test", "claude-opus-5-5", lambda key: client) == status
    assert client.retrieved == ["claude-opus-5-5"]
    assert client.closed
