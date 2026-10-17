"""`action_items.json` of a session (phase 23): the extracted items and their export results."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Sequence

from vozata.domain import ActionItem
from vozata.storage.files.layout import SessionPaths, write_atomic

SCHEMA_VERSION = 1
# Held around every read-modify-write of `action_items.json` (extraction, edits, export).
action_items_lock = threading.RLock()

_log = logging.getLogger(__name__)


def read_action_items(paths: SessionPaths) -> list[ActionItem]:
    """The stored items in order; empty when the file is absent or unreadable."""
    path = paths.action_items_json
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [ActionItem.from_dict(item) for item in data["items"]]
    except (ValueError, KeyError, TypeError) as error:
        _log.warning("Ignoring unreadable %s: %s", path, error)
        return []


def write_action_items(paths: SessionPaths, items: Sequence[ActionItem]) -> None:
    """Replace `action_items.json` atomically."""
    data = {"schema_version": SCHEMA_VERSION, "items": [item.to_dict() for item in items]}
    write_atomic(paths.action_items_json, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
