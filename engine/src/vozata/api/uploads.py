"""A raw request body saved to a file with a size cap (phases 39 and 60): no multipart."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import Request

from vozata.api.errors import ApiError


async def save_body(
    request: Request, destination: Path, limit: int, too_large: Callable[[], ApiError]
) -> None:
    """Stream the body into `destination`; `too_large()` is raised as soon as it is known to be
    bigger than `limit` bytes (from `Content-Length`, else while it arrives)."""
    if int(request.headers.get("content-length") or 0) > limit:
        raise too_large()
    received = 0
    with destination.open("wb") as file:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise too_large()
            file.write(chunk)
