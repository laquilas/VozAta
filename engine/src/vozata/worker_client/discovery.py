"""Find VozAta workers on the local network by a UDP broadcast (phase 47)."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vozata.worker.discovery import MAX_DATAGRAM, REQUEST, Datagrams

DISCOVERY_SECONDS = 1.5
BROADCAST = "255.255.255.255"
POLL_SECONDS = 0.05


@dataclass(frozen=True)
class FoundWorker:
    id: str
    name: str
    url: str
    version: str
    gpu: str | None


def _sending(source: str) -> Datagrams:  # pragma: no cover - a real UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((source, 0))
    sock.settimeout(POLL_SECONDS)
    return sock


def discover_workers(
    port: int,
    sources: Sequence[str],
    *,
    seconds: float = DISCOVERY_SECONDS,
    open_socket: Callable[[str], Datagrams] = _sending,
    clock: Callable[[], float] = time.monotonic,
) -> list[FoundWorker]:
    """Broadcast from every address in `sources` (one per network of this PC, since Windows
    sends a broadcast through one interface only) and collect the answers for `seconds`."""
    sockets: list[Datagrams] = []
    for source in dict.fromkeys(["0.0.0.0", *sources]):
        try:
            sock = open_socket(source)
            sock.sendto(json.dumps(REQUEST).encode(), (BROADCAST, port))
        except OSError:
            continue
        sockets.append(sock)
    found: dict[str, FoundWorker] = {}
    deadline = clock() + seconds
    try:
        while sockets and clock() < deadline:
            for sock in sockets:
                try:
                    data, (host, _) = sock.recvfrom(MAX_DATAGRAM)
                except OSError:  # nothing yet (timeout) or a closed network
                    continue
                worker = _parse(data, host)
                if worker is not None:
                    found.setdefault(worker.id, worker)
    finally:
        for sock in sockets:
            sock.close()
    return sorted(found.values(), key=lambda worker: worker.name.lower())


def _parse(data: bytes, host: str) -> FoundWorker | None:
    try:
        reply = json.loads(data)
        if reply.get("vozata") != "worker" or not reply.get("id"):
            return None
        return FoundWorker(
            id=str(reply["id"]),
            name=str(reply.get("name") or host),
            url=f"http://{host}:{int(reply['port'])}",
            version=str(reply.get("version") or ""),
            gpu=reply.get("gpu"),
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
