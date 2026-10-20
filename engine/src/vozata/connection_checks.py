"""`POST /settings/test/{target}`: check an external service with the saved settings (phase 38).

Each check makes one small read-only request. Secrets go only into request headers: results name
hosts, models, projects and HTTP statuses, never a token, and the log names the target and the
outcome only.
"""

from __future__ import annotations

import base64
import contextlib
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote, urlparse

import httpx

from vozata.config import Settings

_log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HUGGING_FACE = "https://huggingface.co"


class CheckTarget(StrEnum):
    OLLAMA = "ollama"
    STT_API = "stt_api"
    HF_TOKEN = "hf_token"
    AZURE_DEVOPS = "azure_devops"
    GITHUB = "github"


MODEL_TARGETS = frozenset({CheckTarget.OLLAMA})  # tests of a model that may run on the GPU
_NO_PRIORITY = contextlib.nullcontext()


@dataclass(frozen=True)
class CheckResult:
    """`ok` and the locale key (under `settings_test`) of the message, with its parameters."""

    ok: bool
    code: str
    params: dict[str, object] = field(default_factory=dict)


class ConnectionChecks:
    """Runs one check per target; HTTP goes through `transport` (tests: `httpx.MockTransport`)."""

    def __init__(
        self,
        hf_models: Sequence[str],
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        priority: Callable[[Settings], AbstractContextManager[None]] | None = None,
    ) -> None:
        # phase 40: the model tests run under the Config-test GPU priority (`priority(settings)`
        # is a no-op unless the model runs on the local GPU)
        self._priority = priority or (lambda settings: contextlib.nullcontext())
        self._hf_models = tuple(hf_models)  # gated pyannote models the HF token must open
        self._transport = transport
        self._timeout = timeout
        self._checks: dict[CheckTarget, Callable[[httpx.Client, Settings], CheckResult]] = {
            CheckTarget.OLLAMA: _ollama,
            CheckTarget.STT_API: _stt_api,
            CheckTarget.HF_TOKEN: self._hf_token,
            CheckTarget.AZURE_DEVOPS: _azure_devops,
            CheckTarget.GITHUB: _github,
        }

    def run(self, target: CheckTarget, settings: Settings) -> CheckResult:
        try:
            with httpx.Client(
                timeout=self._timeout, transport=self._transport, follow_redirects=False
            ) as client:
                gpu = self._priority(settings) if target in MODEL_TARGETS else _NO_PRIORITY
                with gpu:
                    result = self._checks[target](client, settings)
        except httpx.HTTPError as error:
            host = urlparse(str(error.request.url)).hostname if _has_request(error) else None
            result = CheckResult(False, "unreachable", {"host": host or "?"})
        except (ValueError, KeyError, TypeError, AttributeError):
            result = CheckResult(False, "invalid_response")  # not the JSON the service sends
        _log.info("Connection test %s: %s", target.value, result.code)
        return result

    def _hf_token(self, client: httpx.Client, settings: Settings) -> CheckResult:
        if not settings.hf_token:
            return CheckResult(False, "not_configured", {"keys": "HF_TOKEN"})
        headers = {"Authorization": f"Bearer {settings.hf_token}"}
        for model in self._hf_models:
            status = client.head(
                f"{HUGGING_FACE}/{model}/resolve/main/config.yaml", headers=headers
            ).status_code
            if status == 401:
                return CheckResult(False, "unauthorized", {"status": status})
            if status == 403:
                return CheckResult(False, "terms_not_accepted", {"model": model})
            if status >= 400:
                return CheckResult(False, "http_error", {"status": status})
        return CheckResult(True, "hf_token_ok", {"models": ", ".join(self._hf_models)})


def _has_request(error: httpx.HTTPError) -> bool:
    try:
        error.request  # noqa: B018 - raises when the error has no request
    except RuntimeError:
        return False
    return True


def _ollama(client: httpx.Client, settings: Settings) -> CheckResult:
    response = client.get(settings.ollama_url.rstrip("/") + "/api/tags")
    if response.status_code >= 400:
        return CheckResult(False, "http_error", {"status": response.status_code})
    names = {str(model.get("name")) for model in response.json().get("models", [])}
    model = settings.ollama_model
    if model in names or f"{model}:latest" in names:
        return CheckResult(True, "ollama_ok", {"model": model})
    return CheckResult(False, "ollama_model_missing", {"model": model})


def _stt_api(client: httpx.Client, settings: Settings) -> CheckResult:
    if not settings.openai_stt_url:
        return CheckResult(False, "not_configured", {"keys": "OPENAI_STT_URL"})
    key = settings.openai_stt_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = client.get(settings.openai_stt_url.rstrip("/") + "/models", headers=headers)
    host = urlparse(settings.openai_stt_url).hostname or settings.openai_stt_url
    return _by_status(response.status_code, "stt_api_ok", {"host": host}, host)


def _azure_devops(client: httpx.Client, settings: Settings) -> CheckResult:
    if not (settings.azdo_org_url and settings.azdo_project and settings.azdo_pat):
        return CheckResult(
            False, "not_configured", {"keys": "AZDO_ORG_URL, AZDO_PROJECT, AZDO_PAT"}
        )
    token = base64.b64encode(f":{settings.azdo_pat}".encode()).decode()
    url = f"{settings.azdo_org_url.rstrip('/')}/_apis/projects/{quote(settings.azdo_project)}"
    response = client.get(
        url, params={"api-version": "7.1"}, headers={"Authorization": f"Basic {token}"}
    )
    status = 401 if response.status_code in (203, 302) else response.status_code  # sign-in page
    project = settings.azdo_project
    return _by_status(status, "azure_devops_ok", {"project": project}, project)


def _github(client: httpx.Client, settings: Settings) -> CheckResult:
    if not (settings.github_repo and settings.github_token):
        return CheckResult(False, "not_configured", {"keys": "GITHUB_REPO, GITHUB_TOKEN"})
    response = client.get(
        f"{GITHUB_API}/repos/{settings.github_repo}",
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    repo = settings.github_repo
    return _by_status(response.status_code, "github_ok", {"repo": repo}, repo)


def _by_status(status: int, ok_code: str, params: dict[str, object], what: str) -> CheckResult:
    if status < 300:
        return CheckResult(True, ok_code, params)
    if status in (401, 403):
        return CheckResult(False, "unauthorized", {"status": status})
    if status == 404:
        return CheckResult(False, "not_found", {"what": what})
    return CheckResult(False, "http_error", {"status": status})
