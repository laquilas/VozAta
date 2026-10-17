"""HTTP helpers shared by the task exporters: one POST, failures mapped to `TaskExportError`."""

from __future__ import annotations

from typing import Any

import httpx

from vozata.ports import TaskExportError

DETAIL_CHARS = 200  # error details are cut: a tracker may answer with a whole HTML page


def post_json(client: httpx.Client, url: str, body: Any, headers: dict[str, str]) -> dict[str, Any]:
    """POST `body` as JSON and return the JSON reply; raises `TaskExportError`.

    Credentials travel only in `headers` and never appear in the raised errors.
    """
    try:
        response = client.post(url, json=body, headers=headers)
    except httpx.HTTPError as error:
        raise TaskExportError("unreachable", reason=type(error).__name__) from None
    if response.status_code in (401, 403):
        raise TaskExportError("unauthorized", status=response.status_code)
    if response.status_code == 404:
        raise TaskExportError("not_found", status=response.status_code)
    if response.status_code >= 400:
        detail = _detail(response)
        raise TaskExportError("http_error", status=response.status_code, detail=detail)
    try:
        data = response.json()
    except ValueError:
        raise TaskExportError("invalid_reply") from None
    if not isinstance(data, dict):
        raise TaskExportError("invalid_reply")
    return data


def link(data: dict[str, Any], *path: str) -> str:
    """The string at `path` in a JSON reply; raises `TaskExportError("invalid_reply")`."""
    value: Any = data
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    if not isinstance(value, str) or not value:
        raise TaskExportError("invalid_reply")
    return value


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None
    message = data.get("message") if isinstance(data, dict) else None
    text = message if isinstance(message, str) and message else response.text
    return " ".join(text.split())[:DETAIL_CHARS] or response.reason_phrase
