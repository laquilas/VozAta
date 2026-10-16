"""Retries for remote transcription requests: rate limits, server errors and network failures."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

ATTEMPTS = 3
BASE_DELAY = 1.0  # seconds, doubled after each failed attempt
MAX_DELAY = 30.0


class TranscriptionRequestError(RuntimeError):
    """A remote transcription request kept failing; the message says why (never the API key)."""


def send_with_retry(
    send: Callable[[], httpx.Response],
    *,
    attempts: int = ATTEMPTS,
    base_delay: float = BASE_DELAY,
    max_delay: float = MAX_DELAY,
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    """Call `send` until it answers below 500 and not 429, at most `attempts` times.

    Waits `Retry-After` seconds when given (capped at `max_delay`), else `base_delay`, doubling.
    Other responses (including 4xx) are returned for the caller to handle.
    """
    pause = sleep or time.sleep
    attempt = 1
    while True:
        try:
            response = send()
        except httpx.TransportError as error:  # timeouts and connection failures
            reason, response = str(error), None
        else:
            if response.status_code != 429 and response.status_code < 500:
                return response
            reason = f"HTTP {response.status_code}"
        if attempt >= attempts:
            raise TranscriptionRequestError(
                f"The speech API request failed after {attempts} attempts: {reason}"
            )
        backoff = min(base_delay * 2 ** (attempt - 1), max_delay)
        pause(_retry_after(response, max_delay) or backoff)
        attempt += 1


def _retry_after(response: httpx.Response | None, max_delay: float) -> float | None:
    if response is None:
        return None
    try:
        return min(float(response.headers.get("Retry-After", "")), max_delay)
    except ValueError:
        return None
