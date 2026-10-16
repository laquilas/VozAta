"""Ollama `LanguageModel` over its HTTP chat API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from vozata.ports import LanguageModelError

NUM_CTX = 8192
AVAILABILITY_TIMEOUT = 3.0  # health checks must answer quickly


class OllamaLanguageModel:
    """Chat completions from a local Ollama server (`POST /api/chat`).

    Every failure (unreachable server, HTTP error, timeout, malformed reply) raises
    `LanguageModelError`; callers decide whether the session continues.
    """

    def __init__(
        self,
        url: str,
        model: str,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._client = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        body = self._body(system, prompt, stream=False)
        if json_schema is not None:
            body["format"] = json_schema
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            return str(response.json()["message"]["content"])
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError) as error:
            raise LanguageModelError(f"Ollama chat request failed: {error}") from error

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        try:
            with self._client.stream(
                "POST", "/api/chat", json=self._body(system, prompt, stream=True)
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
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

    def close(self) -> None:
        self._client.close()

    def _body(self, system: str, prompt: str, *, stream: bool) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": stream,
            "options": {"num_ctx": NUM_CTX},
        }
