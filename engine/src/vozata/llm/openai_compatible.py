"""An OpenAI-compatible chat server as the `LanguageModel` (phase 53): LM Studio, vLLM, the
llama.cpp server, Ollama's `/v1`, or OpenAI itself (`POST {url}/chat/completions`)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from vozata.net import url_host
from vozata.ports import LanguageModelError, LlmUnreachableError

AVAILABILITY_TIMEOUT = 3.0  # health checks must answer quickly
_CONNECTION = (httpx.ConnectError, httpx.ConnectTimeout)


class OpenAICompatibleLanguageModel:
    """Chat completions from a server that speaks the OpenAI API, on this PC or elsewhere.

    The first request is a short `GET {url}/models` probe: a server that is off fails in seconds
    (`LlmUnreachableError`), and without `model` the first model it serves is used (LM Studio
    serves the one loaded). Any other failure is a `LanguageModelError`. Nothing is loaded on
    this side, so `release()` does nothing."""

    def __init__(
        self,
        url: str,
        model: str,
        key: str | None = None,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._client = httpx.Client(
            base_url=url.rstrip("/") + "/", headers=headers, timeout=timeout, transport=transport
        )
        self._model = model
        self._host = url_host(url)
        self._probed = False
        self._unreachable: LlmUnreachableError | None = None
        self._cancelled = False

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        try:
            body = self._body(system, prompt, stream=False)
            if json_schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "reply", "schema": json_schema},
                }
            response = self._client.post("chat/completions", json=body)
            response.raise_for_status()
            if self._cancelled:
                raise RuntimeError("cancelled")
            return str(response.json()["choices"][0]["message"]["content"])
        except LanguageModelError:
            raise
        except _CONNECTION as error:
            raise self._lost(error) from error
        except (
            httpx.HTTPError,
            RuntimeError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise LanguageModelError(f"Chat request to {self._host} failed: {error}") from error

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        try:
            body = self._body(system, prompt, stream=True)
            with self._client.stream("POST", "chat/completions", json=body) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if self._cancelled:
                        raise RuntimeError("cancelled")
                    if not line.startswith("data:"):
                        continue  # blank separators and `: comment` keep-alives
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        return
                    event = json.loads(data)
                    if "error" in event:
                        message = event["error"].get("message", event["error"])
                        raise LanguageModelError(f"Chat stream from {self._host} failed: {message}")
                    content = (event.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if content:
                        yield content
        except LanguageModelError:
            raise
        except _CONNECTION as error:
            raise self._lost(error) from error
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError) as error:
            raise LanguageModelError(f"Chat stream from {self._host} failed: {error}") from error

    def is_available(self) -> bool:
        """True when the server answers and serves the model (any model when none is set)."""
        try:
            served = self._served(AVAILABILITY_TIMEOUT)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return False
        return bool(served) if not self._model else self._model in served

    def release(self) -> None:
        """Nothing to free here: the server manages its own memory."""

    def cancel(self) -> None:
        """Abort the call in flight from another thread; it and every later call raise."""
        self._cancelled = True
        self._client.close()

    def close(self) -> None:
        self._client.close()

    def _body(self, system: str, prompt: str, *, stream: bool) -> dict[str, Any]:
        self._probe()
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": stream,
        }

    def _probe(self) -> None:
        """Once: tell an off server from a failing one, and pick the model when none is set."""
        if self._cancelled:
            raise LanguageModelError("cancelled")
        if self._unreachable is not None:
            raise self._unreachable
        if self._probed:
            return
        try:
            served = self._served(AVAILABILITY_TIMEOUT)
        except (*_CONNECTION, httpx.ReadTimeout) as error:
            raise self._lost(error) from error
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            served = []  # the server is there; the chat request reports what is wrong
        if not self._model:
            if not served:
                raise LanguageModelError(
                    f"{self._host} serves no model: set OPENAI_LLM_MODEL or load one"
                )
            self._model = served[0]
        self._probed = True

    def _served(self, timeout: float) -> list[str]:
        response = self._client.get("models", timeout=timeout)
        response.raise_for_status()
        return [str(model["id"]) for model in response.json().get("data", [])]

    def _lost(self, error: httpx.HTTPError) -> LlmUnreachableError:
        self._unreachable = LlmUnreachableError(self._host, str(error) or type(error).__name__)
        return self._unreachable
