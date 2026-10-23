from __future__ import annotations

from pathlib import Path

import pytest

from vozata.domain import RequestEntry
from vozata.storage.files.layout import SessionPaths
from vozata.storage.requests import read_requests, write_requests

ENTRY = RequestEntry("r1", "2026-10-23T10:05:00-03:00", None, "ask", "app", "Who?", "running")


def test_an_unreadable_file_reads_as_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    paths = SessionPaths(tmp_path / "20261023_100000")
    paths.root.mkdir()
    paths.requests_json.write_text("{not json", encoding="utf-8")

    assert read_requests(paths) == []
    assert "Ignoring unreadable" in caplog.text


def test_entries_round_trip_and_none_removes_the_file(tmp_path: Path) -> None:
    paths = SessionPaths(tmp_path / "20261023_100000")
    paths.root.mkdir()

    write_requests(paths, [ENTRY])
    assert read_requests(paths) == [ENTRY]
    write_requests(paths, [])

    assert not paths.requests_json.exists()


def test_from_dict_fills_the_optional_fields() -> None:
    data = {"id": "r", "created_at": "t", "kind": "ask", "source": "voice", "status": "done"}

    entry = RequestEntry.from_dict(data)

    assert (entry.at, entry.text, entry.result_id, entry.message, entry.finished_at) == (
        None,
        "",
        None,
        None,
        None,
    )
    assert RequestEntry.from_dict(ENTRY.to_dict()) == ENTRY
