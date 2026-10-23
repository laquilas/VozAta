"""Is the VozAta worker there? For `GET /health` (phase 44)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

STATUS_TIMEOUT = 3.0  # the health panel must answer quickly


@dataclass(frozen=True)
class WorkerStatus:
    reachable: bool  # answered `/health` with the token
    version: str | None = None
    models: list[str] = field(default_factory=list)  # loaded on the worker


def worker_status(
    url: str, token: str | None, transport: httpx.BaseTransport | None = None
) -> WorkerStatus:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=STATUS_TIMEOUT, transport=transport) as client:
            response = client.get(url.rstrip("/") + "/health", headers=headers)
        if response.status_code != 200:
            return WorkerStatus(False)
        body = response.json()
        return WorkerStatus(True, str(body.get("version")), [str(m) for m in body["models"]])
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return WorkerStatus(False)
