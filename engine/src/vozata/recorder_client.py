"""The engine's client of the recorder process API (phase 61), on the standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = 5.0


class RecorderUnavailableError(ConnectionError):
    """The recorder does not answer (not running, or wedged)."""


class RecorderApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class HttpRecorderClient:
    def __init__(self, port: int, timeout: float = TIMEOUT) -> None:
        self._base = f"http://127.0.0.1:{port}"
        self._timeout = timeout

    def health(self) -> dict[str, Any] | None:
        """The recorder's `/health`, or None when it does not answer."""
        try:
            return self._call("GET", "/health", timeout=1.0)
        except (RecorderUnavailableError, RecorderApiError):
            return None

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/recordings", body)

    def pause(self) -> dict[str, Any]:
        return self._call("POST", "/recordings/current/pause")

    def resume(self) -> dict[str, Any]:
        return self._call("POST", "/recordings/current/resume")

    def stop(self) -> dict[str, Any]:
        return self._call("POST", "/recordings/current/stop", timeout=60.0)

    def update_options(self, options: dict[str, Any]) -> dict[str, Any]:
        return self._call("PATCH", "/recordings/current", {"options": options})

    def _call(
        self, method: str, path: str, body: Any = None, timeout: float | None = None
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self._base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self._timeout) as reply:
                raw = reply.read()
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read() or b"{}").get("error") or {}
            except ValueError:
                detail = {}
            raise RecorderApiError(
                error.code,
                str(detail.get("code", "recorder_error")),
                str(detail.get("message", "")),
            ) from None
        except (OSError, ValueError) as error:
            raise RecorderUnavailableError(str(error)) from None
        return json.loads(raw) if raw else {}
