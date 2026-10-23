from __future__ import annotations

import pytest

from vozata.config import Settings
from vozata.net import ANTHROPIC_URL, is_local_url, llm_model, llm_url, remote_llm_host, url_host


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://LOCALHOST:11434",
        "http://foo.localhost",
        "http://127.0.0.1:11434",
        "http://127.1.2.3",
        "http://[::1]:11434",
        "localhost:11434",
        "",
        "   ",
        "http://0.0.0.0:11434",
        "http://[::]:11434",
        "http://[::ffff:127.0.0.1]:11434",
    ],
)
def test_loopback_empty_and_unspecified_urls_are_local(url: str) -> None:
    assert is_local_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.0.20:11434",
        "192.168.0.20:11434",
        "https://gpu-box.lan/ollama",
        "http://10.0.0.5",
        "http://[fe80::1]:11434",
        "http://gpu-box:11434",
        "http://[::ffff:192.168.0.20]:11434",
    ],
)
def test_any_other_address_is_remote(url: str) -> None:
    assert is_local_url(url) is False


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("http://192.168.0.20:11434/x", "192.168.0.20"),
        ("gpu-box:11434", "gpu-box"),
        ("https://gpu-box.lan/ollama", "gpu-box.lan"),
        ("http://[fe80::1]:11434", "fe80::1"),
        ("", ""),
    ],
)
def test_url_host_is_the_hostname_without_scheme_or_port(url: str, host: str) -> None:
    assert url_host(url) == host


def test_remote_llm_host_names_the_server_transcripts_are_sent_to() -> None:
    settings = Settings(llm_provider="ollama", ollama_url="http://192.168.0.20:11434")

    assert remote_llm_host(settings) == "192.168.0.20"


def test_remote_llm_host_is_none_for_a_local_ollama() -> None:
    settings = Settings(llm_provider="ollama", ollama_url="http://localhost:11434")

    assert remote_llm_host(settings) is None


def test_remote_llm_host_is_none_when_the_provider_is_not_ollama() -> None:
    settings = Settings(llm_provider="fake", ollama_url="http://192.168.0.20:11434")

    assert remote_llm_host(settings) is None


@pytest.mark.parametrize(
    ("values", "host"),
    [
        (
            {"llm_provider": "openai_compatible", "openai_llm_url": "http://192.168.0.9:1234/v1"},
            "192.168.0.9",
        ),
        ({"llm_provider": "openai_compatible", "openai_llm_url": "http://localhost:1234/v1"}, None),
        (
            {"llm_provider": "openai_compatible", "openai_llm_url": "https://api.openai.com/v1"},
            "api.openai.com",
        ),
        ({"llm_provider": "anthropic"}, "api.anthropic.com"),  # always leaves this PC
    ],
)
def test_remote_llm_host_for_every_provider(values: dict[str, str], host: str | None) -> None:
    assert remote_llm_host(Settings(**values)) == host  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values", "url", "model"),
    [
        ({"ollama_url": "http://o:11434", "ollama_model": "qwen"}, "http://o:11434", "qwen"),
        (
            {
                "llm_provider": "openai_compatible",
                "openai_llm_url": "http://s/v1",
                "openai_llm_model": "m",
            },
            "http://s/v1",
            "m",
        ),
        ({"llm_provider": "anthropic", "anthropic_model": "claude-x"}, ANTHROPIC_URL, "claude-x"),
        ({"llm_provider": "fake"}, None, ""),
    ],
)
def test_the_language_model_url_and_model_of_each_provider(
    values: dict[str, str], url: str | None, model: str
) -> None:
    settings = Settings(**values)  # type: ignore[arg-type]

    assert (llm_url(settings), llm_model(settings)) == (url, model)
