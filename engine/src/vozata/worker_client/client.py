"""HTTP client of the VozAta worker: Bearer token, one fail-fast probe, retries (phase 44)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
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


class WorkerRequestError(RuntimeError):
    """The worker answered, with an error (phase 45: a speaker request it could not run)."""


class WorkerTaskUnavailableError(WorkerUnreachableError):
    """The worker answered but does not offer the task (no `HF_TOKEN` or no `translation` extra
    there): callers fall back to this PC exactly as when it does not answer."""


UNAVAILABLE_CODES = ("worker_speakers_unavailable", "worker_translation_unavailable")


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

    # Speakers (phase 45) ------------------------------------------------------------------

    def diarize_start(self, wav: Path, min_speakers: int | None, max_speakers: int | None) -> str:
        """Upload `system.wav` and start a diarization job; returns its id."""
        self.probe()
        params = {
            key: value
            for key, value in (("min_speakers", min_speakers), ("max_speakers", max_speakers))
            if value is not None
        }
        reply = self._call(
            "POST",
            "/diarize",
            params=params,
            content=wav.read_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        return str(reply["job_id"])

    def diarize_status(self, job_id: str) -> dict[str, Any]:
        """`{state: running|done|failed|cancelled, turns, message}`."""
        return self._call("GET", f"/diarize/{job_id}")

    def diarize_cancel(self, job_id: str) -> None:
        """Best effort: a worker that is gone has nothing left to cancel."""
        with contextlib.suppress(httpx.HTTPError):
            self._client.delete(f"/diarize/{job_id}", timeout=PROBE_TIMEOUT)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        self.probe()
        reply = self._call(
            "POST",
            "/embed",
            content=np.asarray(samples, dtype="<f4").tobytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        return np.asarray(reply["vector"], dtype=np.float32)

    def translate(self, text: str, source: str, target: str) -> str:
        """Phase 46: one committed segment through the worker's opus-mt."""
        reply = self._call(
            "POST", "/translate", json={"text": text, "source": source, "target": target}
        )
        return str(reply["text"])

    def _call(self, method: str, path: str, **options: Any) -> dict[str, Any]:
        """One request: no answer is `WorkerUnreachableError`, a refused token a `ConfigError`,
        another HTTP error `WorkerRequestError` with the worker's code."""
        try:
            response = self._client.request(method, path, **options)
        except httpx.TransportError as error:
            raise self._unreachable(error) from error
        self._check_token(response)
        if response.status_code >= 400:
            try:
                code = str(response.json()["error"]["code"])
            except (ValueError, KeyError, TypeError):
                code = f"HTTP {response.status_code}"
            if code in UNAVAILABLE_CODES:
                raise WorkerTaskUnavailableError(self.host, code)
            raise WorkerRequestError(f"The VozAta worker at {self.host} answered {code}")
        return response.json()

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
