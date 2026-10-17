from __future__ import annotations

import base64
import json

import httpx
import pytest

from tests.export.tasks.contract import SECRET, check_error_mapping
from vozata.domain import TaskDraft
from vozata.export.tasks.azure_devops import AzureDevOpsExporter
from vozata.ports import TaskExportError

LINK = "https://dev.azure.com/acme/My%20Project/_workitems/edit/42"


def _exporter(transport: httpx.MockTransport) -> AzureDevOpsExporter:
    return AzureDevOpsExporter(
        "https://dev.azure.com/acme/", "My Project", SECRET, transport=transport
    )


def _created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": 42, "_links": {"html": {"href": LINK}}})


def test_creates_a_task_with_a_json_patch_and_basic_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _created(request)

    exporter = _exporter(httpx.MockTransport(handler))
    url = exporter.create(TaskDraft("Send <the> report", "Line 1\nOwner: Ana", "2026-10-20"))
    exporter.close()

    assert url == LINK
    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == (
        "https://dev.azure.com/acme/My%20Project/_apis/wit/workitems/$Task?api-version=7.1"
    )
    assert request.headers["Content-Type"] == "application/json-patch+json"
    expected = base64.b64encode(f":{SECRET}".encode()).decode()
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert json.loads(request.content) == [
        {"op": "add", "path": "/fields/System.Title", "value": "Send <the> report"},
        {"op": "add", "path": "/fields/System.Description", "value": "Line 1<br>Owner: Ana"},
        {
            "op": "add",
            "path": "/fields/Microsoft.VSTS.Scheduling.DueDate",
            "value": "2026-10-20T00:00:00Z",
        },
    ]


def test_description_is_html_escaped_and_a_free_text_due_date_is_not_a_field() -> None:
    bodies: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _created(request)

    _exporter(httpx.MockTransport(handler)).create(TaskDraft("T", "a < b & c", "next Friday"))

    [patch] = bodies
    assert patch[1]["value"] == "a &lt; b &amp; c"
    assert [operation["path"] for operation in patch] == [
        "/fields/System.Title",
        "/fields/System.Description",
    ]


def test_a_process_without_the_due_date_field_gets_the_task_without_it() -> None:
    bodies: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={"message": "TF51535: Cannot find field DueDate."})
        return _created(request)

    url = _exporter(httpx.MockTransport(handler)).create(TaskDraft("T", "b", "2026-10-20"))

    assert url == LINK
    assert [len(body) for body in bodies] == [3, 2]


def test_a_400_without_a_due_date_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"message": "bad"})

    with pytest.raises(TaskExportError):
        _exporter(httpx.MockTransport(handler)).create(TaskDraft("T", "b"))
    assert calls == [1]


def test_error_mapping() -> None:
    check_error_mapping(_exporter)
