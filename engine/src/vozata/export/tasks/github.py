"""GitHub issues through the REST API with a token."""

from __future__ import annotations

import httpx

from vozata.domain import TaskDraft
from vozata.export.tasks.http import link, post_json

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubIssuesExporter:
    """`POST /repos/{owner}/{name}/issues` with the title and a Markdown body."""

    name = "GitHub"

    def __init__(
        self,
        repo: str,
        token: str,
        api_url: str = API_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = f"{api_url.rstrip('/')}/repos/{repo.strip().strip('/')}/issues"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def create(self, task: TaskDraft) -> str:
        body = {"title": task.title, "body": task.body}
        return link(post_json(self._client, self._url, body, self._headers), "html_url")

    def close(self) -> None:
        self._client.close()
