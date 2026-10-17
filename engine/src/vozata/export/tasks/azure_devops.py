"""Azure DevOps work items (`$Task`) through the REST API 7.1 with a personal access token."""

from __future__ import annotations

import base64
import html
import re
from typing import Any
from urllib.parse import quote

import httpx

from vozata.domain import TaskDraft
from vozata.export.tasks.http import link, post_json
from vozata.ports import TaskExportError

API_VERSION = "7.1"
DUE_FIELD = "/fields/Microsoft.VSTS.Scheduling.DueDate"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class AzureDevOpsExporter:
    """`POST {org}/{project}/_apis/wit/workitems/$Task` with a JSON Patch document.

    Title and description (HTML) are always set; the assignee is left empty. The due date goes to
    `Microsoft.VSTS.Scheduling.DueDate` when it is an ISO date; a process whose Task type has no
    such field answers 400, so the item is created again without it (the due date stays in the
    description).
    """

    name = "Azure DevOps"

    def __init__(
        self,
        org_url: str,
        project: str,
        pat: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = (
            f"{org_url.rstrip('/')}/{quote(project)}/_apis/wit/workitems/$Task"
            f"?api-version={API_VERSION}"
        )
        token = base64.b64encode(f":{pat}".encode()).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json-patch+json",
            "Accept": "application/json",
        }
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def create(self, task: TaskDraft) -> str:
        due = task.due if task.due and _ISO_DATE.fullmatch(task.due) else None
        try:
            return self._post(task, due)
        except TaskExportError as error:
            if due is None or error.params.get("status") != 400:
                raise
        return self._post(task, None)

    def close(self) -> None:
        self._client.close()

    def _post(self, task: TaskDraft, due: str | None) -> str:
        patch: list[dict[str, Any]] = [
            {"op": "add", "path": "/fields/System.Title", "value": task.title},
            {"op": "add", "path": "/fields/System.Description", "value": _html(task.body)},
        ]
        if due is not None:
            patch.append({"op": "add", "path": DUE_FIELD, "value": f"{due}T00:00:00Z"})
        data = post_json(self._client, self._url, patch, self._headers)
        return link(data, "_links", "html", "href")


def _html(text: str) -> str:
    return "<br>".join(html.escape(line) for line in text.splitlines())
