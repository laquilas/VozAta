"""Phase 23 wiring: only configured task export targets are offered."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver, FakeTranscriber
from tests.test_bootstrap import devices  # noqa: F401  (fixture)
from vozata import bootstrap
from vozata.api.action_items_job import ActionItemsJob
from vozata.api.session_manager import StartOptions
from vozata.bootstrap import TASK_EXPORTERS, build_session, build_task_exporter, task_targets
from vozata.config import Settings
from vozata.domain import AppLanguage, SessionStatus
from vozata.export.tasks.azure_devops import AzureDevOpsExporter
from vozata.export.tasks.github import GitHubIssuesExporter
from vozata.minutes.action_items import ActionItemExtractor


def test_the_api_container_extracts_and_exports_with_current_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLanguageModel()
    monkeypatch.setitem(
        bootstrap.TRANSCRIBERS, "fake", lambda settings, downloader: FakeTranscriber()
    )
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: llm)
    shared_seen: list = []
    monkeypatch.setattr(
        bootstrap,
        "build_session",
        lambda settings, observer, **kwargs: shared_seen.append(kwargs["shared"]),
    )
    settings = Settings(
        output_dir=tmp_path / "recordings",
        stt_provider="fake",
        llm_provider="fake",
        whisper_keep_loaded=True,
        app_language=AppLanguage.ES,
        **GITHUB,  # type: ignore[arg-type]
    )

    container = bootstrap.build_api_container(settings, tmp_path / ".env")

    assert isinstance(container.extract_action_items, ActionItemsJob)
    container.manager._factory(FakeSessionObserver(), StartOptions())
    [shared] = shared_seen
    shared.lease(keep=True).close()  # an idle, kept Whisper
    extractor = container.extract_action_items._build()  # idle: Whisper is freed first
    assert isinstance(extractor, ActionItemExtractor)
    assert extractor._llm is llm
    assert extractor._t("minutes.output_language") == "español"
    assert not shared.loaded
    shared.lease(keep=True)
    container.manager._session = SimpleNamespace(status=SessionStatus.RECORDING)
    container.extract_action_items._build()  # a recording uses Whisper right now: keep it
    assert shared.loaded
    assert container.task_targets() == ["github"]
    assert isinstance(container.task_exporter("github"), GitHubIssuesExporter)
    assert container.task_exporter("azure_devops") is None


@pytest.mark.usefixtures("devices")
def test_sessions_extract_action_items_only_with_minutes_and_the_flag(tmp_path: Path) -> None:
    def extractor(**overrides: object) -> object:
        settings = Settings(output_dir=tmp_path, **overrides)  # type: ignore[arg-type]
        return build_session(settings, FakeSessionObserver())._c.action_items

    assert isinstance(extractor(), ActionItemExtractor)
    assert extractor(extract_action_items=False) is None
    assert extractor(generate_minutes=False) is None


AZDO = {"azdo_org_url": "https://dev.azure.com/acme", "azdo_project": "P", "azdo_pat": "pat"}
GITHUB = {"github_repo": "acme/vozata", "github_token": "ghp"}


def test_registry_has_both_targets() -> None:
    assert list(TASK_EXPORTERS) == ["azure_devops", "github"]


def test_nothing_is_offered_without_credentials() -> None:
    assert task_targets(Settings()) == []
    assert task_targets(Settings(azdo_org_url="https://x", azdo_project="P")) == []
    assert task_targets(Settings(github_repo="acme/vozata")) == []


def test_only_configured_targets_are_offered() -> None:
    assert task_targets(Settings(**GITHUB)) == ["github"]
    assert task_targets(Settings(**AZDO, **GITHUB)) == ["azure_devops", "github"]


def test_build_task_exporter_builds_configured_targets_only() -> None:
    settings = Settings(**AZDO, **GITHUB)

    assert isinstance(build_task_exporter(settings, "azure_devops"), AzureDevOpsExporter)
    assert isinstance(build_task_exporter(settings, "github"), GitHubIssuesExporter)
    assert build_task_exporter(settings, "jira") is None
    assert build_task_exporter(Settings(**GITHUB), "azure_devops") is None
