"""A minimal JSON + Server-Sent Events server on the standard library (phase 61).

The recorder must start in about a second, so it does not import FastAPI / uvicorn. Routes are
`(method, pattern)` → handler; a handler gets the path parameters and the JSON body and returns
a `Response` (or a `Stream` for `text/event-stream`). Errors use the engine's envelope:
`{"error": {"code", "message"}}`.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class Response:
    status: int = 200
    body: Any = None  # JSON-serializable; None = no body


@dataclass(frozen=True)
class Stream:
    """`events()` yields `(event, data)` pairs, or None for a keep-alive comment."""

    events: Callable[[], Iterator[tuple[str, Any] | None]]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


Handler = Callable[[dict[str, str], Any], "Response | Stream"]


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
        self._routes.append((method, re.compile(f"^{regex}$"), handler))

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str]]:
        allowed = False
        for route_method, regex, handler in self._routes:
            match = regex.match(path)
            if match:
                if route_method == method:
                    return handler, match.groupdict()
                allowed = True
        if allowed:
            raise ApiError(405, "method_not_allowed", f"{method} is not allowed on {path}")
        raise ApiError(404, "not_found", f"No route for {path}")


class RecorderServer(ThreadingHTTPServer):
    """Loopback only, one process per port: Windows' SO_REUSEADDR would let a second recorder
    bind the same port, so the server asks for an exclusive bind instead."""

    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, port: int, router: Router) -> None:
        self.router = router
        super().__init__(("127.0.0.1", port), _Handler)

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if sys.platform == "win32" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that closes a kept-alive connection is normal; log anything else."""
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        _log.exception("Request from %s failed", client_address)


class _Handler(BaseHTTPRequestHandler):
    server: RecorderServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _log.debug("%s %s", self.address_string(), format % args)

    def _dispatch(self, method: str) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            handler, params = self.server.router.resolve(method, path)
            result = handler(params, self._body())
        except ApiError as error:
            self._json(error.status, {"error": {"code": error.code, "message": error.message}})
            return
        except Exception as error:  # never let a request take the recorder down
            _log.exception("%s %s failed", method, path)
            self._json(500, {"error": {"code": "internal_error", "message": str(error)}})
            return
        if isinstance(result, Stream):
            self._stream(result)
        else:
            self._json(result.status, result.body)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "body_too_large", "The request body is too large")
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "invalid_json", "The request body is not JSON") from None

    def _json(self, status: int, body: Any) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, stream: Stream) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for item in stream.events():
                if item is None:
                    chunk = ": keep-alive\n\n"
                else:
                    event, data = item
                    chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the client went away
