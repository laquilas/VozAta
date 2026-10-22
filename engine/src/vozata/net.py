"""Where a configured server lives: this PC or another one (phase 43)."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from vozata.config import Settings


def url_host(url: str) -> str:
    """The host name of `url` (no scheme, port or path), or the raw text when none parses.

    A URL without a scheme, such as `192.168.0.20:11434`, is read as `http://…`.
    """
    text = url.strip()
    return _hostname(text) or text


def is_local_url(url: str) -> bool:
    """Whether `url` points at this PC: loopback names and addresses only.

    An empty or unparsable URL and an unspecified address (`0.0.0.0`, `::`) count as local, so
    the phase 40 GPU rules keep applying. This PC's own LAN address is remote on purpose.
    """
    host = _hostname(url.strip())
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # a name such as `gpu-box`
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def remote_llm_host(settings: Settings) -> str | None:
    """The host transcripts are sent to, or None when the language model runs on this PC."""
    if settings.llm_provider != "ollama" or is_local_url(settings.ollama_url):
        return None
    return url_host(settings.ollama_url)


def _hostname(text: str) -> str | None:
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"http://{text}")
    return parsed.hostname
