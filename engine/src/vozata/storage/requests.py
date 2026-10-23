"""`requests.json` of a session (phase 59): the meeting's request history."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from vozata.domain import RequestEntry
from vozata.storage.files.layout import SessionPaths, write_atomic

SCHEMA_VERSION = 1

_log = logging.getLogger(__name__)


def read_requests(paths: SessionPaths) -> list[RequestEntry]:
    """The stored requests, oldest first; empty when the file is absent or unreadable."""
    path = paths.requests_json
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [RequestEntry.from_dict(item) for item in data["items"]]
    except (ValueError, KeyError, TypeError) as error:
        _log.warning("Ignoring unreadable %s: %s", path, error)
        return []


def write_requests(paths: SessionPaths, items: Sequence[RequestEntry]) -> None:
    """Replace `requests.json` atomically; no items, no file."""
    if not items:
        paths.requests_json.unlink(missing_ok=True)
        return
    data = {"schema_version": SCHEMA_VERSION, "items": [item.to_dict() for item in items]}
    write_atomic(paths.requests_json, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
