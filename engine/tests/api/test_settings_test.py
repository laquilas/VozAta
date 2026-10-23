from __future__ import annotations

import base64
import contextlib
import dataclasses
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from tests.api.conftest import Api
from vozata.config import Settings
from vozata.connection_checks import CheckResult, CheckTarget, ConnectionChecks
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuGate, GpuUser

HF_MODELS = ("pyannote/speaker-diarization-community-1", "pyannote/wespeaker-voxceleb-resnet34-LM")
SECRETS = (
    "sk-stt-secret",
    "hf_secret_token",
    "azdo-secret-pat",
    "ghp_secret_token",
    "wk-secret-token",
    "sk-openai-llm-secret",
    "sk-ant-secret",
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ollama_url": "http://ollama.test:11434",
        "ollama_model": "qwen2.5:7b",
        "openai_stt_url": "https://stt.example.com/v1",
        "openai_stt_key": "sk-stt-secret",
        "hf_token": "hf_secret_token",
        "azdo_org_url": "https://dev.azure.com/contoso",
        "azdo_project": "Voz Ata",
        "azdo_pat": "azdo-secret-pat",
        "github_repo": "contoso/vozata",
        "github_token": "ghp_secret_token",
        "worker_url": "http://gpu-pc:8766",
        "worker_token": "wk-secret-token",
        "openai_llm_url": "http://lmstudio.test:1234/v1",
        "openai_llm_key": "sk-openai-llm-secret",
        "openai_llm_model": "qwen2.5-7b-instruct",
        "anthropic_api_key": "sk-ant-secret",
        "anthropic_model": "claude-opus-5-5",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _run(
    target: CheckTarget,
    handler: Callable[[httpx.Request], httpx.Response],
    settings: Settings | None = None,
) -> tuple[CheckResult, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    checks = ConnectionChecks(HF_MODELS, transport=httpx.MockTransport(record))
    return checks.run(target, settings or _settings()), seen


def _status(code: int, **kwargs: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(code, **kwargs)  # type: ignore[arg-type]


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


# Ollama


def test_ollama_success_when_the_model_is_pulled() -> None:
    result, seen = _run(CheckTarget.OLLAMA, _status(200, json={"models": [{"name": "qwen2.5:7b"}]}))

    assert result == CheckResult(True, "ollama_ok", {"model": "qwen2.5:7b"})
    assert str(seen[0].url) == "http://ollama.test:11434/api/tags"


def test_ollama_accepts_the_latest_tag() -> None:
    settings = _settings(ollama_model="llama3")
    result, _ = _run(
        CheckTarget.OLLAMA, _status(200, json={"models": [{"name": "llama3:latest"}]}), settings
    )

    assert result.ok


def test_ollama_reports_a_missing_model() -> None:
    result, _ = _run(CheckTarget.OLLAMA, _status(200, json={"models": [{"name": "other"}]}))

    assert result == CheckResult(False, "ollama_model_missing", {"model": "qwen2.5:7b"})


def test_ollama_server_error() -> None:
    result, _ = _run(CheckTarget.OLLAMA, _status(500))

    assert result == CheckResult(False, "http_error", {"status": 500})


def test_ollama_unreachable_names_the_host() -> None:
    result, _ = _run(CheckTarget.OLLAMA, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "ollama.test"})


def test_a_reply_that_is_not_json_is_an_invalid_response() -> None:
    result, _ = _run(CheckTarget.OLLAMA, _status(200, text="<html>"))

    assert result == CheckResult(False, "invalid_response")


def test_an_error_without_a_request_names_no_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from vozata import connection_checks

    def fail(client: httpx.Client, settings: Settings) -> CheckResult:
        raise httpx.TransportError("socket closed")  # raised outside a request: no `.request`

    checks = ConnectionChecks(HF_MODELS)
    monkeypatch.setitem(checks._checks, CheckTarget.OLLAMA, fail)  # noqa: SLF001

    assert checks.run(CheckTarget.OLLAMA, _settings()) == CheckResult(
        False, "unreachable", {"host": "?"}
    )
    assert connection_checks._has_request(httpx.TransportError("x")) is False  # noqa: SLF001


# Speech-to-text API


def test_stt_api_success_sends_the_key_as_bearer() -> None:
    result, seen = _run(CheckTarget.STT_API, _status(200, json={"data": []}))

    assert result == CheckResult(True, "stt_api_ok", {"host": "stt.example.com"})
    assert str(seen[0].url) == "https://stt.example.com/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer sk-stt-secret"


def test_stt_api_without_a_key_sends_no_authorization() -> None:
    _, seen = _run(CheckTarget.STT_API, _status(200), _settings(openai_stt_key=None))

    assert "Authorization" not in seen[0].headers


@pytest.mark.parametrize("status", [401, 403])
def test_stt_api_rejected_key(status: int) -> None:
    result, _ = _run(CheckTarget.STT_API, _status(status))

    assert result == CheckResult(False, "unauthorized", {"status": status})


def test_stt_api_unreachable() -> None:
    result, _ = _run(CheckTarget.STT_API, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "stt.example.com"})


def test_stt_api_without_a_url_is_not_configured() -> None:
    result, seen = _run(CheckTarget.STT_API, _status(200), _settings(openai_stt_url=""))

    assert result == CheckResult(False, "not_configured", {"keys": "OPENAI_STT_URL"})
    assert seen == []


# Hugging Face token


def test_hf_token_success_checks_every_gated_model() -> None:
    result, seen = _run(CheckTarget.HF_TOKEN, _status(200))

    assert result.ok and result.code == "hf_token_ok"
    assert [request.method for request in seen] == ["HEAD", "HEAD"]
    assert [request.url.path for request in seen] == [
        f"/{model}/resolve/main/config.yaml" for model in HF_MODELS
    ]
    assert seen[0].headers["Authorization"] == "Bearer hf_secret_token"


def test_hf_token_redirect_to_the_file_is_success() -> None:
    result, _ = _run(CheckTarget.HF_TOKEN, _status(302, headers={"Location": "https://cdn"}))

    assert result.ok


def test_hf_token_invalid() -> None:
    result, _ = _run(CheckTarget.HF_TOKEN, _status(401))

    assert result == CheckResult(False, "unauthorized", {"status": 401})


def test_hf_token_terms_not_accepted_names_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if "wespeaker" in request.url.path else 200)

    result, _ = _run(CheckTarget.HF_TOKEN, handler)

    assert result == CheckResult(False, "terms_not_accepted", {"model": HF_MODELS[1]})


def test_hf_token_other_error() -> None:
    result, _ = _run(CheckTarget.HF_TOKEN, _status(500))

    assert result == CheckResult(False, "http_error", {"status": 500})


def test_hf_token_unreachable() -> None:
    result, _ = _run(CheckTarget.HF_TOKEN, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "huggingface.co"})


def test_hf_token_missing() -> None:
    result, seen = _run(CheckTarget.HF_TOKEN, _status(200), _settings(hf_token=None))

    assert result == CheckResult(False, "not_configured", {"keys": "HF_TOKEN"})
    assert seen == []


# Azure DevOps


def test_azure_devops_success_reads_the_project_with_basic_auth() -> None:
    result, seen = _run(CheckTarget.AZURE_DEVOPS, _status(200, json={"name": "Voz Ata"}))

    assert result == CheckResult(True, "azure_devops_ok", {"project": "Voz Ata"})
    assert seen[0].url.raw_path.startswith(b"/contoso/_apis/projects/Voz%20Ata?")
    assert seen[0].url.params["api-version"] == "7.1"
    expected = base64.b64encode(b":azdo-secret-pat").decode()
    assert seen[0].headers["Authorization"] == f"Basic {expected}"


@pytest.mark.parametrize("status", [401, 203, 302])
def test_azure_devops_rejected_token(status: int) -> None:
    result, _ = _run(CheckTarget.AZURE_DEVOPS, _status(status))

    assert result == CheckResult(False, "unauthorized", {"status": 401})


def test_azure_devops_unknown_project() -> None:
    result, _ = _run(CheckTarget.AZURE_DEVOPS, _status(404))

    assert result == CheckResult(False, "not_found", {"what": "Voz Ata"})


def test_azure_devops_unreachable() -> None:
    result, _ = _run(CheckTarget.AZURE_DEVOPS, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "dev.azure.com"})


def test_azure_devops_not_configured() -> None:
    result, _ = _run(CheckTarget.AZURE_DEVOPS, _status(200), _settings(azdo_pat=None))

    assert not result.ok and result.code == "not_configured"


# GitHub


def test_github_success() -> None:
    result, seen = _run(CheckTarget.GITHUB, _status(200, json={"full_name": "contoso/vozata"}))

    assert result == CheckResult(True, "github_ok", {"repo": "contoso/vozata"})
    assert str(seen[0].url) == "https://api.github.com/repos/contoso/vozata"
    assert seen[0].headers["Authorization"] == "Bearer ghp_secret_token"


def test_github_rejected_token() -> None:
    result, _ = _run(CheckTarget.GITHUB, _status(401))

    assert result == CheckResult(False, "unauthorized", {"status": 401})


def test_github_unknown_repository() -> None:
    result, _ = _run(CheckTarget.GITHUB, _status(404))

    assert result == CheckResult(False, "not_found", {"what": "contoso/vozata"})


def test_github_server_error() -> None:
    result, _ = _run(CheckTarget.GITHUB, _status(502))

    assert result == CheckResult(False, "http_error", {"status": 502})


def test_github_unreachable() -> None:
    result, _ = _run(CheckTarget.GITHUB, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "api.github.com"})


def test_github_not_configured() -> None:
    result, _ = _run(CheckTarget.GITHUB, _status(200), _settings(github_repo=None))

    assert result == CheckResult(False, "not_configured", {"keys": "GITHUB_REPO, GITHUB_TOKEN"})


# VozAta worker (phase 44)

WORKER_HEALTH = {
    "worker": "ok",
    "version": "0.9.0",
    "gpu": {"available": True, "name": "RTX 4070", "vram_total_mb": 12282},
    "capabilities": ["speech"],
    "models": [],
}


def test_worker_success_names_its_version_and_gpu() -> None:
    result, seen = _run(CheckTarget.WORKER, _status(200, json=WORKER_HEALTH))

    assert result == CheckResult(
        True, "worker_ok", {"host": "gpu-pc", "version": "0.9.0", "gpu": "RTX 4070"}
    )
    assert str(seen[0].url) == "http://gpu-pc:8766/health"
    assert seen[0].headers["Authorization"] == "Bearer wk-secret-token"


def test_a_worker_without_a_gpu_says_cpu() -> None:
    body = {**WORKER_HEALTH, "gpu": {"available": False, "name": None, "vram_total_mb": None}}

    result, _ = _run(CheckTarget.WORKER, _status(200, json=body))

    assert result.params["gpu"] == "CPU"


def test_worker_without_a_token_sends_no_authorization() -> None:
    _, seen = _run(
        CheckTarget.WORKER, _status(200, json=WORKER_HEALTH), _settings(worker_token=None)
    )

    assert "Authorization" not in seen[0].headers


def test_worker_refused_token() -> None:
    result, _ = _run(CheckTarget.WORKER, _status(401))

    assert result == CheckResult(False, "unauthorized", {"status": 401})


def test_worker_unreachable() -> None:
    result, _ = _run(CheckTarget.WORKER, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "gpu-pc"})


def test_worker_not_configured() -> None:
    result, _ = _run(CheckTarget.WORKER, _status(200), _settings(worker_url=None))

    assert result == CheckResult(False, "not_configured", {"keys": "WORKER_URL"})


# OpenAI-compatible language model and Anthropic (phase 53)


def _served(*names: str) -> Callable[[httpx.Request], httpx.Response]:
    return _status(200, json={"object": "list", "data": [{"id": name} for name in names]})


def test_openai_llm_success_when_the_model_is_served() -> None:
    result, seen = _run(CheckTarget.OPENAI_LLM, _served("qwen2.5-7b-instruct"))

    assert result == CheckResult(
        True, "openai_llm_ok", {"host": "lmstudio.test", "model": "qwen2.5-7b-instruct"}
    )
    assert str(seen[0].url) == "http://lmstudio.test:1234/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer sk-openai-llm-secret"


def test_openai_llm_reports_a_model_the_server_does_not_serve() -> None:
    result, _ = _run(CheckTarget.OPENAI_LLM, _served("llama-3"))

    assert result == CheckResult(
        False, "openai_llm_model_missing", {"host": "lmstudio.test", "model": "qwen2.5-7b-instruct"}
    )


def test_openai_llm_without_a_model_names_the_first_one_served() -> None:
    result, _ = _run(CheckTarget.OPENAI_LLM, _served("llama-3"), _settings(openai_llm_model=""))

    assert result == CheckResult(
        True, "openai_llm_ok", {"host": "lmstudio.test", "model": "llama-3"}
    )


def test_openai_llm_without_a_key_sends_no_authorization() -> None:
    _, seen = _run(
        CheckTarget.OPENAI_LLM, _served("qwen2.5-7b-instruct"), _settings(openai_llm_key=None)
    )

    assert "Authorization" not in seen[0].headers


@pytest.mark.parametrize(("status", "code"), [(401, "unauthorized"), (500, "http_error")])
def test_openai_llm_http_errors(status: int, code: str) -> None:
    result, _ = _run(CheckTarget.OPENAI_LLM, _status(status))

    assert (result.ok, result.code) == (False, code)


def test_openai_llm_unreachable() -> None:
    result, _ = _run(CheckTarget.OPENAI_LLM, _refused)

    assert result == CheckResult(False, "unreachable", {"host": "lmstudio.test"})


def _anthropic(
    status: int | None, settings: Settings | None = None
) -> tuple[CheckResult, list[tuple[str, str]]]:
    asked: list[tuple[str, str]] = []

    def probe(key: str, model: str) -> int | None:
        asked.append((key, model))
        return status

    checks = ConnectionChecks(HF_MODELS, anthropic_probe=probe)
    return checks.run(CheckTarget.ANTHROPIC, settings or _settings()), asked


def test_anthropic_success_retrieves_the_model_with_the_key() -> None:
    result, asked = _anthropic(200)

    assert result == CheckResult(True, "anthropic_ok", {"model": "claude-opus-5-5"})
    assert asked == [("sk-ant-secret", "claude-opus-5-5")]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, CheckResult(False, "unauthorized", {"status": 401})),
        (404, CheckResult(False, "not_found", {"what": "claude-opus-5-5"})),
        (529, CheckResult(False, "http_error", {"status": 529})),
        (None, CheckResult(False, "unreachable", {"host": "api.anthropic.com"})),
    ],
)
def test_anthropic_failures(status: int | None, expected: CheckResult) -> None:
    assert _anthropic(status)[0] == expected


def test_anthropic_without_a_key_asks_nothing() -> None:
    result, asked = _anthropic(200, _settings(anthropic_api_key=None))

    assert result == CheckResult(False, "not_configured", {"keys": "ANTHROPIC_API_KEY"})
    assert asked == []


def test_without_an_anthropic_probe_the_check_is_unavailable() -> None:
    result, _ = _run(CheckTarget.ANTHROPIC, _status(200))

    assert result == CheckResult(False, "unavailable")


# Secrets


@pytest.mark.parametrize("target", list(CheckTarget))
@pytest.mark.parametrize("code", [200, 401, 403, 404, 500])
def test_secrets_are_never_in_results_or_logs(
    target: CheckTarget, code: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    result, _ = _run(target, _status(code, json={"models": []}))

    text = repr(result) + caplog.text
    assert not any(secret in text for secret in SECRETS)


# API


def _checks_api(api: Api, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    checks = ConnectionChecks(HF_MODELS, transport=httpx.MockTransport(handler))
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, connection_check=checks.run)


def test_the_test_endpoint_returns_a_localized_message(api: Api) -> None:
    _checks_api(api, _status(200, json={"models": [{"name": "qwen2.5:7b"}]}))

    response = api.client.post("/settings/test/ollama")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "message": "Ollama answered and the model qwen2.5:7b is installed.",
    }


def test_the_test_endpoint_uses_the_saved_settings(api: Api, tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404)

    _checks_api(api, handler)
    api.client.put("/settings", json={"values": {"GITHUB_REPO": "me/repo", "GITHUB_TOKEN": "t0k"}})

    body = api.client.post("/settings/test/github").json()

    assert body["ok"] is False
    assert "me/repo" in body["message"]
    assert "t0k" not in body["message"]
    assert seen[0].headers["Authorization"] == "Bearer t0k"


def test_the_test_endpoint_rejects_an_unknown_target(api: Api) -> None:
    response = api.client.post("/settings/test/smtp")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_without_checks_the_endpoint_says_unavailable(api: Api) -> None:
    body = api.client.post("/settings/test/github").json()

    assert body == {"ok": False, "message": "Connection tests are not available in this engine."}


@pytest.mark.parametrize("language", ["en", "pt-BR", "es"])
def test_every_result_code_has_a_message_in_every_language(language: str) -> None:
    from vozata.domain import AppLanguage
    from vozata.i18n import TomlLocalizer

    localizer = TomlLocalizer(AppLanguage(language))
    params = {
        "model": "m",
        "host": "h",
        "models": "a, b",
        "project": "p",
        "repo": "r",
        "keys": "K",
        "status": 401,
        "what": "w",
        "version": "v",
        "gpu": "g",
    }
    for code in (
        "ollama_ok",
        "ollama_model_missing",
        "stt_api_ok",
        "hf_token_ok",
        "azure_devops_ok",
        "github_ok",
        "worker_ok",
        "openai_llm_ok",
        "openai_llm_model_missing",
        "anthropic_ok",
        "not_configured",
        "unauthorized",
        "terms_not_accepted",
        "not_found",
        "http_error",
        "unreachable",
        "invalid_response",
        "unavailable",
    ):
        text = localizer.t(f"settings_test.{code}", **params)
        assert text and not text.startswith("settings_test.")


def test_connection_check_holds_check_priority() -> None:
    held: list[bool] = []
    entered: list[Settings] = []

    @contextlib.contextmanager
    def priority(settings: Settings) -> Iterator[None]:
        entered.append(settings)
        held.append(True)
        try:
            yield
        finally:
            held.append(False)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, held[-1] if held else False))
        if request.url.host == "ollama.test":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
        return httpx.Response(200, json={})

    seen: list[tuple[str | None, bool]] = []
    checks = ConnectionChecks(
        HF_MODELS,
        transport=httpx.MockTransport(handler),
        priority=priority,
        model_targets=frozenset({CheckTarget.OLLAMA}),  # a future model-loading check opts in
    )
    settings = _settings()

    assert checks.run(CheckTarget.OLLAMA, settings).ok
    assert checks.run(CheckTarget.GITHUB, settings).ok

    assert seen == [("ollama.test", True), ("api.github.com", False)]  # only the model test
    assert entered == [settings]


def test_the_ollama_check_does_not_cancel_a_running_llm_step() -> None:
    gate = GpuGate()
    token = CancelToken()

    def tags(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})

    checks = ConnectionChecks(
        HF_MODELS,
        transport=httpx.MockTransport(tags),
        priority=lambda settings: gate.priority(GpuUser.CHECK),
    )
    with gate.queue_step(token, lambda: None):  # the queue's minutes generation runs
        result = checks.run(CheckTarget.OLLAMA, _settings())

    assert result.ok
    assert not token.cancelled  # it only lists the pulled models: nothing loads on the GPU
