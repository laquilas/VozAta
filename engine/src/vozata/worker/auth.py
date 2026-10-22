"""Bearer-token check of the worker's API (phase 44): it listens on the local network."""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

UNAUTHORIZED = "worker_unauthorized"


class Unauthorized(Exception):
    """A request without the worker's token."""


def token_guard(token: str | None) -> Callable[[Request], None]:
    """A dependency that accepts only `Authorization: Bearer <token>`; None lets everyone in (a
    worker on loopback, where only this PC can reach it)."""
    expected = f"Bearer {token}".encode() if token else None

    def guard(request: Request) -> None:
        if expected is None:
            return
        given = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(given, expected):
            raise Unauthorized

    return guard


def unauthorized(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": UNAUTHORIZED}},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )
