"""Shared `TaskExporter` contract: every exporter maps HTTP failures the same way."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from vozata.domain import TaskDraft
from vozata.ports import TaskExporter, TaskExportError

Handler = Callable[[httpx.Request], httpx.Response]
ExporterFactory = Callable[[httpx.MockTransport], TaskExporter]
SECRET = "s3cr3t-token"
DRAFT = TaskDraft("Send the report", "From the meeting.\nOwner: Ana")


def _failure(factory: ExporterFactory, handler: Handler) -> TaskExportError:
    exporter = factory(httpx.MockTransport(handler))
    assert isinstance(exporter, TaskExporter)
    with pytest.raises(TaskExportError) as caught:
        exporter.create(DRAFT)
    assert SECRET not in str(caught.value)
    return caught.value


def check_error_mapping(factory: ExporterFactory) -> None:
    for status in (401, 403):
        error = _failure(factory, lambda request, s=status: httpx.Response(s))
        assert (error.code, error.params) == ("unauthorized", {"status": status})

    assert _failure(factory, lambda request: httpx.Response(404)).code == "not_found"

    error = _failure(factory, lambda request: httpx.Response(422, json={"message": "Bad  title"}))
    assert (error.code, error.params) == ("http_error", {"status": 422, "detail": "Bad title"})

    error = _failure(factory, lambda request: httpx.Response(500, text="x" * 500))
    assert error.code == "http_error"
    assert error.params["detail"] == "x" * 200

    error = _failure(factory, lambda request: httpx.Response(502))
    assert error.params["detail"] == "Bad Gateway"

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused with {SECRET}")

    error = _failure(factory, unreachable)
    assert (error.code, error.params) == ("unreachable", {"reason": "ConnectError"})

    for reply in (httpx.Response(201, text="<html>"), httpx.Response(201, json=[1])):
        assert _failure(factory, lambda request, r=reply: r).code == "invalid_reply"
    assert _failure(factory, lambda request: httpx.Response(201, json={})).code == "invalid_reply"
