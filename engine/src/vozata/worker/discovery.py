"""The worker's answer to VozAta engines looking for workers on the network (phase 47)."""

from __future__ import annotations

import json
import logging
import socket
import threading
from collections.abc import Callable
from typing import Protocol

_log = logging.getLogger(__name__)

REQUEST = {"vozata": "discover", "v": 1}
MAX_DATAGRAM = 2048
POLL_SECONDS = 0.5  # how often the responder thread checks that it should stop


class Datagrams(Protocol):
    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]: ...

    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...

    def close(self) -> None: ...


def is_request(data: bytes) -> bool:
    try:
        return json.loads(data) == REQUEST
    except (ValueError, UnicodeDecodeError):
        return False


def _listening(port: int) -> Datagrams:  # pragma: no cover - a real UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    sock.settimeout(POLL_SECONDS)
    return sock


class DiscoveryResponder:
    """Answers `REQUEST` with `reply()` (id, name, port, version, gpu: no secret) on its own
    thread; anything else is ignored."""

    def __init__(
        self,
        port: int,
        reply: Callable[[], dict[str, object]],
        open_socket: Callable[[int], Datagrams] = _listening,
    ) -> None:
        self._port = port
        self._reply = reply
        self._open = open_socket
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: Datagrams | None = None

    def start(self) -> None:
        try:
            self._socket = self._open(self._port)
        except OSError as error:
            _log.warning("Worker discovery is off: UDP port %s: %s", self._port, error)
            return
        self._thread = threading.Thread(target=self._serve, name="worker-discovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._socket is not None:
            self._socket.close()

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                data, sender = self._socket.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            if is_request(data):
                answer = {"vozata": "worker", "v": 1, **self._reply()}
                self._socket.sendto(json.dumps(answer).encode(), sender)
