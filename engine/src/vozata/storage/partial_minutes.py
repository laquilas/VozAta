"""`partial_minutes.json` of a session (phase 48): minutes of parts of the meeting."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from vozata.domain import PartialMinutes
from vozata.storage.files.layout import SessionPaths, write_atomic

SCHEMA_VERSION = 1

_log = logging.getLogger(__name__)


def read_partial_minutes(paths: SessionPaths) -> list[PartialMinutes]:
    """The stored items, oldest first; empty when the file is absent or unreadable."""
    path = paths.partial_minutes_json
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [PartialMinutes.from_dict(item) for item in data["items"]]
    except (ValueError, KeyError, TypeError) as error:
        _log.warning("Ignoring unreadable %s: %s", path, error)
        return []


def write_partial_minutes(paths: SessionPaths, items: Sequence[PartialMinutes]) -> None:
    """Replace `partial_minutes.json` atomically; no items, no file."""
    if not items:
        paths.partial_minutes_json.unlink(missing_ok=True)
        return
    data = {"schema_version": SCHEMA_VERSION, "items": [item.to_dict() for item in items]}
    write_atomic(paths.partial_minutes_json, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
