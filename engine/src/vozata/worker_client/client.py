"""HTTP client of the VozAta worker: Bearer token, one fail-fast probe, retries (phase 44)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import numpy as np

from vozata.config import ConfigError
from vozata.domain import TranscriptionResult, Word
from vozata.ports import WorkerUnreachableError
from vozata.transcription.retry import TranscriptionRequestError, send_with_retry

PROBE_TIMEOUT = 3.0  # an off worker must fail in seconds, not after the request timeout
CONNECT_TIMEOUT = 3.0
REQUEST_TIMEOUT = 120.0  # a long chunk on a busy GPU
_UNANSWERED = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


class WorkerClient:
    """One client per transcriber. The first request is a short `GET /health`, so a worker that is
    off raises `WorkerUnreachableError` in seconds; a refused token is a `ConfigError` on
    `WORKER_TOKEN` (a setup error the user must fix, not a reason to fall back)."""

    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.host = urlparse(url).hostname or url
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=url,
            headers=headers,
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),
            transport=transport,
        )
        self._sleep = sleep
        self._probed = False

    def probe(self) -> None:
        if self._probed:
            return
        try:
            response = self._client.get("/health", timeout=PROBE_TIMEOUT)
        except _UNANSWERED as error:
            raise self._unreachable(error) from error
        self._check_token(response)
        self._probed = True

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None,
        prompt: str | None,
    ) -> TranscriptionResult:
        if not np.any(samples):
            return TranscriptionResult(words=(), language=language)  # silence costs nothing
        self.probe()
        headers = {
            name: quote(value)
            for name, value in (("X-Hints", hints), ("X-Prompt", prompt))
            if value and value.strip()
        }
        body = np.asarray(samples, dtype="<f4").tobytes()
        try:
            response = send_with_retry(
                lambda: self._client.post(
                    "/transcribe",
                    params={"language": language or ""},
                    content=body,
                    headers={"Content-Type": "application/octet-stream", **headers},
                ),
                sleep=self._sleep,
            )
        except TranscriptionRequestError as error:
            if isinstance(error.__cause__, httpx.TransportError):
                raise self._unreachable(error.__cause__) from error
            raise
        self._check_token(response)
        if response.status_code >= 400:
            raise TranscriptionRequestError(
                f"The VozAta worker at {self.host} answered HTTP {response.status_code}"
            )
        return _result(response.json())

    def close(self) -> None:
        self._client.close()

    def _check_token(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ConfigError("WORKER_TOKEN", "********", "worker_unauthorized", host=self.host)

    def _unreachable(self, error: Exception) -> WorkerUnreachableError:
        return WorkerUnreachableError(self.host, str(error) or type(error).__name__)


def _result(reply: dict[str, Any]) -> TranscriptionResult:
    return TranscriptionResult(
        words=tuple(Word.from_dict(word) for word in reply.get("words", [])),
        language=reply.get("language"),
        avg_logprob=reply.get("avg_logprob"),
    )
