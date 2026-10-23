"""Pair this engine with a worker: its 6-digit code buys the token (phase 47)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from vozata.ports import WorkerUnreachableError

PAIR_TIMEOUT = 5.0
_REFUSALS = {"worker_pairing_refused", "worker_pairing_locked", "worker_no_token"}


@dataclass(frozen=True)
class PairedWorker:
    id: str | None
    name: str
    token: str


class PairingRefusedError(Exception):
    """The worker refused the code; `code` is its error code (refused, locked, no token)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def pair_with_worker(
    url: str, code: str, transport: httpx.BaseTransport | None = None
) -> PairedWorker:
    host = urlparse(url).hostname or url
    try:
        with httpx.Client(timeout=PAIR_TIMEOUT, transport=transport) as client:
            response = client.post(url.rstrip("/") + "/pair", json={"code": code})
        body = response.json()
    except httpx.HTTPError as error:
        raise WorkerUnreachableError(host, str(error) or type(error).__name__) from error
    except ValueError as error:  # not the worker's JSON: something else listens there
        raise WorkerUnreachableError(host, "not a VozAta worker") from error
    if response.status_code != 200:
        refusal = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
        if refusal in _REFUSALS:
            raise PairingRefusedError(refusal)
        raise WorkerUnreachableError(host, f"HTTP {response.status_code}")
    return PairedWorker(id=body.get("id"), name=str(body.get("name") or host), token=body["token"])
