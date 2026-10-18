from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import pytest

from tests.api.conftest import Api
from vozata.settings_options import (
    OLLAMA_TIMEOUT,
    OptionLists,
    SettingOption,
    SettingsOptions,
)

PROVIDERS = {"stt_providers": ["openai_compatible", "faster_whisper"], "llm_providers": ["ollama"]}


def _cache(tmp_path: Path, *repositories: str, empty: tuple[str, ...] = ()) -> Path:
    hub = tmp_path / "hub"
    for repository in repositories:
        (hub / f"models--{repository.replace('/', '--')}" / "snapshots" / "abc123").mkdir(
            parents=True
        )
    for repository in empty:  # a download that never finished: no snapshot
        (hub / f"models--{repository.replace('/', '--')}" / "blobs").mkdir(parents=True)
    return hub


def _tags(*names: str) -> httpx.MockTransport:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": name} for name in names]})

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


def _options(
    tmp_path: Path,
    transport: httpx.BaseTransport | None = None,
    gpu: bool = True,
    hub: Path | None = None,
) -> SettingsOptions:
    return SettingsOptions(
        PROVIDERS,
        hub if hub is not None else _cache(tmp_path),
        lambda: "http://ollama.test:11434/",
        lambda: gpu,
        transport=transport or _tags(),
    )


def test_provider_lists_come_from_the_registries_sorted(tmp_path: Path) -> None:
    lists = _options(tmp_path).collect()

    assert [item.value for item in lists.options["stt_providers"]] == [
        "faster_whisper",
        "openai_compatible",
    ]
    assert lists.options["llm_providers"] == [SettingOption("ollama", "ollama", True)]


def test_whisper_models_are_available_only_when_cached(tmp_path: Path) -> None:
    hub = _cache(
        tmp_path,
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        empty=("Systran/faster-whisper-small",),
    )

    models = {item.value: item for item in _options(tmp_path, hub=hub).whisper_models()}

    assert models["large-v3-turbo"].available
    assert not models["small"].available  # no snapshot yet
    assert not models["large-v3"].available
    assert "tiny" in models and "distil-large-v3" in models


def test_other_cached_whisper_repositories_are_listed_and_other_models_are_not(
    tmp_path: Path,
) -> None:
    hub = _cache(
        tmp_path,
        "Systran/faster-whisper-large-v3",
        "deepdml/faster-whisper-large-v3-turbo-ct2",
        "pyannote/speaker-diarization-community-1",
    )

    values = [item.value for item in _options(tmp_path, hub=hub).whisper_models()]

    assert "deepdml/faster-whisper-large-v3-turbo-ct2" in values
    assert "Systran/faster-whisper-large-v3" not in values  # already listed as large-v3
    assert not any("pyannote" in value for value in values)


def test_a_missing_model_cache_lists_every_known_model_as_not_downloaded(tmp_path: Path) -> None:
    models = _options(tmp_path, hub=tmp_path / "nowhere").whisper_models()

    assert models and not any(item.available for item in models)


def test_cuda_is_unavailable_without_a_gpu(tmp_path: Path) -> None:
    with_gpu = {item.value: item.available for item in _options(tmp_path, gpu=True).devices()}
    without = {item.value: item.available for item in _options(tmp_path, gpu=False).devices()}

    assert with_gpu == {"auto": True, "cuda": True, "cpu": True}
    assert without == {"auto": True, "cuda": False, "cpu": True}


def test_compute_types_are_a_fixed_list(tmp_path: Path) -> None:
    values = [item.value for item in _options(tmp_path).collect().options["compute_types"]]

    assert values[:3] == ["default", "auto", "int8"]
    assert "float16" in values


def test_ollama_models_are_the_pulled_ones(tmp_path: Path) -> None:
    transport = _tags("qwen2.5:7b", "llama3.2:3b")

    lists = _options(tmp_path, transport).collect()

    assert [item.value for item in lists.options["ollama_models"]] == ["llama3.2:3b", "qwen2.5:7b"]
    assert lists.reachable == {"ollama_models": True}
    assert str(transport.seen[0].url) == "http://ollama.test:11434/api/tags"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused", request=request)),
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, json={"models": [{"size": 1}]}),
    ],
    ids=["unreachable", "server-error", "not-json", "no-name"],
)
def test_an_unreachable_ollama_gives_an_empty_list_never_an_error(tmp_path: Path, handler) -> None:  # type: ignore[no-untyped-def]
    lists = _options(tmp_path, httpx.MockTransport(handler)).collect()

    assert lists.options["ollama_models"] == []
    assert lists.reachable == {"ollama_models": False}


def test_the_ollama_request_has_a_short_timeout() -> None:
    assert OLLAMA_TIMEOUT <= 2.0


def test_get_options_returns_every_source(api: Api) -> None:
    lists = OptionLists(
        {
            "whisper_models": [SettingOption("large-v3", "large-v3", False)],
            "ollama_models": [],
        },
        {"ollama_models": False},
    )
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, setting_options=lambda: lists)

    response = api.client.get("/settings/options")

    assert response.status_code == 200
    assert response.json() == {
        "options": {
            "whisper_models": [{"value": "large-v3", "label": "large-v3", "available": False}],
            "ollama_models": [],
        },
        "reachable": {"ollama_models": False},
    }


def test_get_options_without_a_catalog_is_empty(api: Api) -> None:
    assert api.client.get("/settings/options").json() == {"options": {}, "reachable": {}}


def test_bootstrap_lists_every_registry() -> None:
    from vozata.bootstrap import build_setting_options
    from vozata.config import Settings

    options = build_setting_options(
        lambda: Settings(ollama_url="http://127.0.0.1:9"), lambda: False
    )

    sources = options._providers  # noqa: SLF001 - the wiring is what this test checks
    assert set(sources) == {
        "stt_providers",
        "llm_providers",
        "diarization_providers",
        "translation_providers",
    }
    assert "faster_whisper" in sources["stt_providers"]
    assert "ollama" in sources["llm_providers"]
