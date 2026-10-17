"""Phase 23 wiring: only configured task export targets are offered."""

from __future__ import annotations

from vozata.bootstrap import TASK_EXPORTERS, build_task_exporter, task_targets
from vozata.config import Settings
from vozata.export.tasks.azure_devops import AzureDevOpsExporter
from vozata.export.tasks.github import GitHubIssuesExporter

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
