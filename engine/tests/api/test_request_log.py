"""The request history of a meeting (phase 59)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.api.conftest import RecordingBroadcaster
from vozata.api.request_log import MAX_ENTRIES, RequestLog
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

BRT = timezone(timedelta(hours=-3))


class _Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.store = FileSessionRepository(SessionStore(tmp_path))
        self.session_id = self.store.create()
        self.broadcaster = RecordingBroadcaster()
        ids = iter(f"r{n}" for n in range(1, 1000))
        self.clock = [datetime(2026, 10, 23, 10, 0, 0, tzinfo=BRT)]
        self.log = RequestLog(
            self.store, self.broadcaster, now=lambda: self.clock[0], new_id=lambda: next(ids)
        )

    def statuses(self) -> list[tuple[str, str]]:
        return [(entry.id, entry.status) for entry in self.store.read_requests(self.session_id)]

    def events(self) -> list[dict[str, object]]:
        return [data["request"] for _, data in self.broadcaster.of("request_updated")]


def test_a_request_is_kept_and_published(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    request_id = rig.log.begin(
        rig.session_id, "minutes_so_far", "voice", text="gere a ata", at=312.46, status="recognized"
    )

    [entry] = rig.store.read_requests(rig.session_id)
    assert request_id == "r1" == entry.id
    assert (entry.kind, entry.source, entry.text, entry.at, entry.status) == (
        "minutes_so_far",
        "voice",
        "gere a ata",
        312.5,
        "recognized",
    )
    assert entry.created_at == "2026-10-23T10:00:00-03:00"
    assert entry.finished_at is None
    assert rig.events() == [entry.to_dict()]
    assert rig.broadcaster.of("request_updated")[0][0] == rig.session_id


def test_update_changes_one_entry_and_stamps_the_end(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    first = rig.log.begin(rig.session_id, "minutes_so_far", "voice", status="recognized")
    rig.log.begin(rig.session_id, "ask", "app", text="Who?")
    rig.log.update(rig.session_id, first, "running")
    rig.clock[0] += timedelta(seconds=40)

    rig.log.update(rig.session_id, first, "done", result_id="p1")

    entry = rig.store.read_requests(rig.session_id)[0]
    assert (entry.status, entry.result_id, entry.finished_at) == (
        "done",
        "p1",
        "2026-10-23T10:00:40-03:00",
    )
    assert rig.statuses() == [("r1", "done"), ("r2", "running")]
    assert [event["status"] for event in rig.events()] == [
        "recognized",
        "running",
        "running",
        "done",
    ]


def test_finish_pending_finishes_the_latest_unfinished_of_a_kind(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.log.begin(rig.session_id, "minutes", "app", status="done")
    rig.log.begin(rig.session_id, "minutes", "app")
    rig.log.begin(rig.session_id, "action_items", "app")

    rig.log.finish_pending(
        rig.session_id, frozenset({"minutes"}), "failed", message="llm_unreachable"
    )

    assert rig.statuses() == [("r1", "done"), ("r2", "failed"), ("r3", "running")]
    assert rig.store.read_requests(rig.session_id)[1].message == "llm_unreachable"


def test_finish_result_matches_the_answer(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.log.begin(rig.session_id, "ask", "voice", result_id="voice-a")
    rig.log.begin(rig.session_id, "ask", "app", result_id="b")

    rig.log.finish_result(rig.session_id, "voice-a", "done")

    assert rig.statuses() == [("r1", "done"), ("r2", "running")]


def test_nothing_to_finish_publishes_nothing(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.log.finish_pending(rig.session_id, frozenset({"minutes"}), "done")
    rig.log.update(rig.session_id, "missing", "done")

    assert rig.events() == []
    assert rig.store.read_requests(rig.session_id) == []


def test_a_finished_request_has_its_end_at_once(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.log.begin(
        rig.session_id, "minutes", "app", status="ignored", message="session_still_active"
    )

    [entry] = rig.store.read_requests(rig.session_id)
    assert entry.finished_at == entry.created_at


def test_the_history_keeps_the_latest_entries(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    for _ in range(MAX_ENTRIES + 3):
        rig.log.begin(rig.session_id, "ask", "app")

    entries = rig.store.read_requests(rig.session_id)
    assert len(entries) == MAX_ENTRIES
    assert entries[0].id == "r4"


def test_a_storage_failure_does_not_break_the_request(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rig = _Rig(tmp_path)

    def broken(session_id: str) -> list[object]:
        raise OSError("disk full")

    rig.store.read_requests = broken  # type: ignore[method-assign]

    rig.log.begin(rig.session_id, "ask", "app")

    assert "could not be saved" in caplog.text
    assert len(rig.events()) == 1
