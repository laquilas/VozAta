"""Ollama `LanguageModel` over its HTTP chat API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from vozata.net import url_host
from vozata.ports import LanguageModelError, LlmUnreachableError

NUM_CTX = 8192
AVAILABILITY_TIMEOUT = 3.0  # health checks must answer quickly
RELEASE_TIMEOUT = 10.0  # the unload after a cancel must not hang the next recording
JOB_KEEP_ALIVE = "5m"  # keeps the model loaded between the calls of one job (map-reduce)


class OllamaLanguageModel:
    """Chat completions from an Ollama server on this PC or another one (`POST /api/chat`).

    Every failure (unreachable server, HTTP error, timeout, malformed reply) raises
    `LanguageModelError`; callers decide whether the session continues. A server that does not
    answer at all raises `LlmUnreachableError`: the first request of a model is a short
    `GET /api/tags` probe, so an Ollama PC that is off fails in seconds, not after the 300 s
    chat timeout (phase 43).

    Chat requests keep the model loaded for `JOB_KEEP_ALIVE`; `release()` then applies
    `keep_alive` (`OLLAMA_KEEP_ALIVE`, default `0`: unload at once) so the GPU is free for Whisper.
    """

    def __init__(
        self,
        url: str,
        model: str,
        keep_alive: str = "0",
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self.keep_alive = keep_alive
        self._client = httpx.Client(base_url=url, timeout=timeout, transport=transport)
        self._cancelled = False
        self._url, self._transport = url, transport
        self._host = url_host(url)
        self._probed = False
        self._unreachable: LlmUnreachableError | None = None

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        body = self._body(system, prompt, stream=False)
        if json_schema is not None:
            body["format"] = json_schema
        try:
            self._probe()
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            if self._cancelled:
                raise RuntimeError("cancelled")
            return str(response.json()["message"]["content"])
        except LlmUnreachableError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise self._lost(error) from error
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError) as error:
            raise LanguageModelError(f"Ollama chat request failed: {error}") from error

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        try:
            self._probe()
            with self._client.stream(
                "POST", "/api/chat", json=self._body(system, prompt, stream=True)
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if self._cancelled:
                        raise RuntimeError("cancelled")
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LanguageModelError(f"Ollama stream failed: {data['error']}")
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        return
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise self._lost(error) from error
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            if isinstance(error, LanguageModelError):
                raise
            raise LanguageModelError(f"Ollama stream failed: {error}") from error

    def is_available(self) -> bool:
        """True when the server answers and the configured model is pulled."""
        try:
            response = self._client.get("/api/tags", timeout=AVAILABILITY_TIMEOUT)
            response.raise_for_status()
            names = {model["name"] for model in response.json().get("models", [])}
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
            return False
        return self._model in names or f"{self._model}:latest" in names

    def release(self) -> None:
        """Apply `keep_alive` now: an empty chat is Ollama's way to unload (or re-time) a model.

        After `cancel()` the model is always unloaded (`keep_alive` 0), whatever
        `OLLAMA_KEEP_ALIVE` says: a cancel means a live recording or Ask needs the GPU now."""
        if self._unreachable is not None:
            return  # nothing is loaded there to unload, and waiting would hold the queue
        keep_alive = 0 if self._cancelled else _keep_alive(self.keep_alive)
        body = {"model": self._model, "messages": [], "keep_alive": keep_alive}
        try:
            if self._cancelled:  # the main client is closed: unload through a short-lived one
                with httpx.Client(
                    base_url=self._url, timeout=RELEASE_TIMEOUT, transport=self._transport
                ) as client:
                    client.post("/api/chat", json=body).raise_for_status()
            else:
                self._client.post("/api/chat", json=body).raise_for_status()
        except (httpx.HTTPError, RuntimeError) as error:
            raise LanguageModelError(f"Ollama release failed: {error}") from error

    def cancel(self) -> None:
        """Abort the call in flight from another thread; it and every later call raise."""
        self._cancelled = True
        self._client.close()

    def close(self) -> None:
        self._client.close()

    def _probe(self) -> None:
        """Once per model: a short `GET /api/tags` that tells an off server from a failing one.

        Only a connection failure counts; any HTTP answer, even an error, means the server is
        there and the chat request reports what is wrong with it."""
        if self._unreachable is not None:
            raise self._unreachable
        if self._probed:
            return
        try:
            self._client.get("/api/tags", timeout=AVAILABILITY_TIMEOUT)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as error:
            raise self._lost(error) from error
        except httpx.HTTPError:
            pass
        self._probed = True

    def _lost(self, error: httpx.HTTPError) -> LlmUnreachableError:
        self._unreachable = LlmUnreachableError(self._host, str(error) or type(error).__name__)
        return self._unreachable

    def _body(self, system: str, prompt: str, *, stream: bool) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": stream,
            "options": {"num_ctx": NUM_CTX},
            "keep_alive": JOB_KEEP_ALIVE,
        }


def _keep_alive(value: str) -> int | str:
    """Whole seconds go as a JSON number: Ollama parses a string as a Go duration (units needed)."""
    try:
        return int(value)
    except ValueError:
        return value
