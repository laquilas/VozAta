"""What the worker app on the worker PC shows about itself (phase 47)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass

Resolver = Callable[[str], list[str]]


@dataclass(frozen=True)
class WorkerIdentity:
    id: str | None  # `WORKER_ID`; None for a loopback worker (nobody on the network finds it)
    name: str  # `WORKER_NAME`, else the host name
    port: int


def _resolve(host: str) -> list[str]:  # pragma: no cover - the network stack of the PC
    return [info[4][0] for info in socket.getaddrinfo(host, None, socket.AF_INET)]


def lan_addresses(resolve: Resolver = _resolve, host: str | None = None) -> list[str]:
    """This PC's IPv4 addresses another PC can use: no loopback, no link-local (169.254)."""
    try:
        found = resolve(host or socket.gethostname())
    except OSError:
        return []
    usable = []
    for text in dict.fromkeys(found):
        address = ipaddress.ip_address(text)
        if not (address.is_loopback or address.is_link_local):
            usable.append(text)
    return usable


def is_loopback_client(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
