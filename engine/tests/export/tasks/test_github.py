from __future__ import annotations

import json

import httpx

from tests.export.tasks.contract import SECRET, check_error_mapping
from vozata.domain import TaskDraft
from vozata.export.tasks.github import GitHubIssuesExporter

LINK = "https://github.com/acme/vozata/issues/7"


def _exporter(transport: httpx.MockTransport) -> GitHubIssuesExporter:
    return GitHubIssuesExporter(" acme/vozata/ ", SECRET, transport=transport)


def test_creates_an_issue_with_the_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"number": 7, "html_url": LINK})

    exporter = _exporter(httpx.MockTransport(handler))
    url = exporter.create(TaskDraft("Send the report", "From the meeting.", "2026-10-20"))
    exporter.close()

    assert url == LINK
    [request] = requests
    assert (request.method, str(request.url)) == (
        "POST",
        "https://api.github.com/repos/acme/vozata/issues",
    )
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert json.loads(request.content) == {"title": "Send the report", "body": "From the meeting."}


def test_error_mapping() -> None:
    check_error_mapping(_exporter)
