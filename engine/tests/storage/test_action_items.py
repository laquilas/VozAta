from __future__ import annotations

import json
from pathlib import Path

from vozata.domain import ActionItem
from vozata.storage.action_items import read_action_items, write_action_items
from vozata.storage.session_store import SessionPaths

ITEM = ActionItem("a1", "Send the report", "Ana", "2026-10-20", ("mic-000042",))


def _paths(tmp_path: Path) -> SessionPaths:
    root = tmp_path / "20261015_202358"
    root.mkdir()
    return SessionPaths(root)


def test_items_round_trip_with_their_export_url(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    exported = ActionItem("a2", "Book the room", exported_url="https://example.test/1")

    write_action_items(paths, [ITEM, exported])

    assert read_action_items(paths) == [ITEM, exported]
    data = json.loads(paths.action_items_json.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["items"][0] == {
        "id": "a1",
        "description": "Send the report",
        "owner": "Ana",
        "due": "2026-10-20",
        "source_segment_ids": ["mic-000042"],
        "exported_url": None,
    }


def test_a_missing_file_has_no_items(tmp_path: Path) -> None:
    assert read_action_items(_paths(tmp_path)) == []


def test_an_unreadable_file_is_ignored(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.action_items_json.write_text("{not json", encoding="utf-8")
    assert read_action_items(paths) == []
    paths.action_items_json.write_text('{"items": [{"id": "a1"}]}', encoding="utf-8")
    assert read_action_items(paths) == []


def test_from_dict_turns_blank_and_non_text_values_into_none() -> None:
    item = ActionItem.from_dict(
        {"id": 1, "description": "Call", "owner": "  ", "due": 5, "exported_url": " u "}
    )
    assert item == ActionItem("1", "Call", None, None, (), "u")
