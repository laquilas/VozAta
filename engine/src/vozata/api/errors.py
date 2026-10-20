"""Error envelope `{"error": {"code", "message"}}` with messages localized by `APP_LANGUAGE`."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from vozata.api.session_manager import (
    NoActiveSessionError,
    SessionConflictError,
    SessionNotInterruptedError,
    SessionStillActiveError,
)
from vozata.config import ConfigError
from vozata.ports import Localizer, SessionNotFoundError
from vozata.session import SessionStartError

_log = logging.getLogger(__name__)


class ApiError(Exception):
    """An expected failure: HTTP status + stable code; message from `errors.api.<code>`."""

    def __init__(self, status: int, code: str, **params: object) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI, localizer: Localizer) -> None:
    def respond(http_status: int, code: str, message: str | None = None, **params: object):
        text = message if message is not None else localizer.t(f"errors.api.{code}", **params)
        return JSONResponse(error_body(code, text), status_code=http_status)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return respond(error.status, error.code, **error.params)

    @app.exception_handler(SessionConflictError)
    async def conflict(request: Request, error: SessionConflictError) -> JSONResponse:
        return respond(409, "session_already_active")

    @app.exception_handler(NoActiveSessionError)
    async def no_session(request: Request, error: NoActiveSessionError) -> JSONResponse:
        return respond(409, "no_active_session")

    @app.exception_handler(SessionNotInterruptedError)
    async def not_interrupted(request: Request, error: SessionNotInterruptedError) -> JSONResponse:
        return respond(409, "session_not_interrupted", id=str(error))

    @app.exception_handler(SessionStillActiveError)
    async def still_active(request: Request, error: SessionStillActiveError) -> JSONResponse:
        return respond(409, "session_still_active", id=str(error))

    @app.exception_handler(SessionNotFoundError)
    async def not_found(request: Request, error: SessionNotFoundError) -> JSONResponse:
        return respond(404, "session_not_found", id=str(error))

    @app.exception_handler(SessionStartError)
    async def start_failed(request: Request, error: SessionStartError) -> JSONResponse:
        return respond(503, error.code, message=str(error))

    @app.exception_handler(ConfigError)
    async def bad_config(request: Request, error: ConfigError) -> JSONResponse:
        return respond(500, "invalid_configuration", message=error.render(localizer))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        return respond(422, "invalid_request", details=details)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
        return respond(error.status_code, code, status=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        _log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return respond(500, "internal_error")
