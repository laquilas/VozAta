"""Anthropic (Claude) as the `LanguageModel` (phase 53), through the official `anthropic` SDK.

Every request is streamed (long minutes stay clear of HTTP timeouts), runs at effort `medium`
and opts into the server-side refusal fallbacks. The transcript always leaves this PC.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

import anthropic

from vozata.net import ANTHROPIC_URL, url_host
from vozata.ports import LanguageModelError, LlmUnreachableError

MAX_TOKENS = 64000  # streamed, so a large ceiling is safe
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
HOST = url_host(ANTHROPIC_URL)
ClientFactory = Callable[[str], Any]  # API key -> an `anthropic.Anthropic`-like client


def sdk_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, max_retries=2)


def probe_status(
    api_key: str, model: str, client_factory: ClientFactory = sdk_client
) -> int | None:
    """The Config test (phase 53): the HTTP status of looking the model up with the key, None
    when the API did not answer."""
    client = client_factory(api_key)
    try:
        client.models.retrieve(model)
    except anthropic.APIStatusError as error:
        return error.status_code
    except anthropic.APIConnectionError:
        return None
    finally:
        client.close()
    return 200


class AnthropicLanguageModel:
    """Claude through the Messages API. A connection failure is `LlmUnreachableError`; an API
    error, a timeout, a refusal or a reply cut at `max_tokens` is a `LanguageModelError`. Without
    a key nothing is sent. Nothing is loaded on this PC, so `release()` does nothing."""

    def __init__(
        self, api_key: str | None, model: str, client_factory: ClientFactory = sdk_client
    ) -> None:
        self._model = model
        self._client = client_factory(api_key) if api_key else None
        self._cancelled = False

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        with self._errors(), self._open(system, prompt, json_schema) as stream:
            message = stream.get_final_message()
        self._check(message)
        return "".join(block.text for block in message.content if block.type == "text")

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        with self._errors(), self._open(system, prompt, None) as stream:
            for text in stream.text_stream:
                if self._cancelled:
                    raise LanguageModelError("cancelled")
                yield text
            message = stream.get_final_message()
        self._check(message)

    def is_available(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.models.retrieve(self._model)
        except anthropic.AnthropicError:
            return False
        return True

    def release(self) -> None:
        """Nothing to free on this PC."""

    def cancel(self) -> None:
        """Abort the call in flight from another thread; it and every later call raise."""
        self._cancelled = True
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _open(self, system: str, prompt: str, json_schema: dict | None) -> Any:
        if self._cancelled:
            raise LanguageModelError("cancelled")
        if self._client is None:
            raise LanguageModelError("Set ANTHROPIC_API_KEY to use Claude")
        output: dict[str, Any] = {"effort": EFFORT}
        if json_schema is not None:
            output["format"] = {"type": "json_schema", "schema": _closed(json_schema)}
        return self._client.beta.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

    def _errors(self) -> _ErrorMap:
        return _ErrorMap(lambda: self._cancelled)

    @staticmethod
    def _check(message: Any) -> None:
        if message.stop_reason == "refusal":
            details = message.stop_details
            category = getattr(details, "category", None) or "unspecified"
            raise LanguageModelError(f"Claude declined the request ({category})")
        if message.stop_reason == "max_tokens":
            raise LanguageModelError(f"Claude's reply was cut at max_tokens ({MAX_TOKENS})")


class _ErrorMap:
    """Turns SDK errors into the port's errors (a context manager around each call)."""

    def __init__(self, cancelled: Callable[[], bool]) -> None:
        self._cancelled = cancelled

    def __enter__(self) -> None:
        return None

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, _: Any
    ) -> bool:
        if error is None or isinstance(error, LanguageModelError):
            return False
        if self._cancelled():
            raise LanguageModelError("cancelled") from error
        if isinstance(error, anthropic.APITimeoutError):
            raise LanguageModelError(f"Claude did not answer in time: {error}") from error
        if isinstance(error, anthropic.APIConnectionError):
            raise LlmUnreachableError(HOST, str(error)) from error
        if isinstance(error, anthropic.APIStatusError):
            raise LanguageModelError(
                f"Anthropic API error {error.status_code}: {error.message}"
            ) from error
        if isinstance(error, anthropic.AnthropicError):
            raise LanguageModelError(f"Anthropic request failed: {error}") from error
        return False


def _closed(schema: dict) -> dict:
    """A copy of `schema` whose objects allow no other properties (structured outputs need it)."""
    result = copy.deepcopy(schema)

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(result)
    return result
