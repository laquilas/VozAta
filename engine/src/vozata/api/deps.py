"""FastAPI dependencies: routes receive the `ApiContainer` stored on the app."""

from __future__ import annotations

from fastapi import Request

from vozata.api.container import ApiContainer


def container(request: Request) -> ApiContainer:
    return request.app.state.container
