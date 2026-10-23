"""Where a configured server lives: this PC or another one (phase 43)."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from vozata.config import Settings

ANTHROPIC_URL = "https://api.anthropic.com"  # the transcripts always leave this PC


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


def llm_url(settings: Settings) -> str | None:
    """The server of the `LLM_PROVIDER` language model (phase 53); None for an unknown provider."""
    urls = {
        "ollama": settings.ollama_url,
        "openai_compatible": settings.openai_llm_url,
        "anthropic": ANTHROPIC_URL,
    }
    return urls.get(settings.llm_provider)


def llm_model(settings: Settings) -> str:
    """The model the `LLM_PROVIDER` language model runs (phase 53); empty for an unknown one."""
    models = {
        "ollama": settings.ollama_model,
        "openai_compatible": settings.openai_llm_model,
        "anthropic": settings.anthropic_model,
    }
    return models.get(settings.llm_provider, "")


def remote_llm_host(settings: Settings) -> str | None:
    """The host transcripts are sent to, or None when the language model runs on this PC."""
    url = llm_url(settings)
    if url is None or is_local_url(url):
        return None
    return url_host(url)


def _hostname(text: str) -> str | None:
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"http://{text}")
    return parsed.hostname
