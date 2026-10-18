"""`GET /sessions?from=&to=` (phase 36): meetings grouped by local start day with totals."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.api.conftest import Api
from vozata.api.session_days import group_by_day, local_bounds, local_day
from vozata.domain import ActionItem, StorageInfo
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

BRT = timezone(timedelta(hours=-3))


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute).astimezone()


def _meeting(api: Api, start: datetime, seconds: float, **meta: Any) -> str:
    session_id = api.store.create(start)
    api.store.write_meta(
        session_id,
        {
            "id": session_id,
            "status": "done",
            "started_at": start.isoformat(),
            "ended_at": (start + timedelta(seconds=seconds)).isoformat(),
            "duration_seconds": seconds,
            "language": "en",
            **meta,
        },
    )
    return session_id


def _week(api: Api, first: str = "2026-10-12", last: str = "2026-10-18") -> dict[str, Any]:
    response = api.client.get("/sessions", params={"from": first, "to": last})
    assert response.status_code == 200, response.text
    return response.json()


def test_meetings_are_grouped_by_day_newest_first_with_totals(api: Api) -> None:
    monday = _meeting(api, _local(2026, 10, 12, 9), 1800)
    morning = _meeting(api, _local(2026, 10, 14, 9), 3600, title="Weekly sync")
    afternoon = _meeting(api, _local(2026, 10, 14, 15, 30), 600.5)
    _meeting(api, _local(2026, 10, 19, 0, 0), 60)  # next week
    _meeting(api, _local(2026, 10, 11, 23, 59), 60)  # last week

    body = _week(api)

    assert [day["date"] for day in body["days"]] == ["2026-10-14", "2026-10-12"]
    wednesday = body["days"][0]
    assert [item["id"] for item in wednesday["items"]] == [afternoon, morning]
    assert wednesday["total_seconds"] == 4200.5
    assert wednesday["items"][1]["title"] == "Weekly sync"
    assert body["days"][1]["items"][0]["id"] == monday
    assert body["total_seconds"] == 6000.5
    assert body["has_earlier"] is True
    assert body["storage"] == "files"


def test_a_meeting_crossing_midnight_stays_on_its_start_day(api: Api) -> None:
    late = _meeting(api, _local(2026, 10, 15, 23, 30), 5400)  # ends at 01:00 on the 16th

    body = _week(api, "2026-10-16", "2026-10-16")
    assert body["days"] == []
    assert body["has_earlier"] is True

    body = _week(api, "2026-10-15", "2026-10-15")
    assert body["days"][0]["date"] == "2026-10-15"
    assert body["days"][0]["items"][0]["id"] == late
    assert body["days"][0]["total_seconds"] == 5400


def test_an_empty_range_without_older_meetings(api: Api) -> None:
    _meeting(api, _local(2026, 10, 20, 10), 60)

    body = _week(api)

    assert body == {"days": [], "total_seconds": 0, "has_earlier": False, "storage": "files"}


def test_the_summary_tells_speakers_action_items_and_template(api: Api) -> None:
    session_id = _meeting(api, _local(2026, 10, 13, 10), 900, template="daily")
    api.store.write_speakers(session_id, ["system:1", "system:2"])
    api.store.write_action_items(session_id, [ActionItem("a1", "Send the deck")])

    item = _week(api)["days"][0]["items"][0]

    assert item["speaker_count"] == 2
    assert item["has_action_items"] is True
    assert item["template"] == "daily"
    assert item["duration_seconds"] == 900


def test_the_live_session_is_listed_with_its_live_duration(api: Api) -> None:
    api.factory.sessions.clear()
    today = date.today()
    started = api.client.post("/sessions", json={})
    assert started.status_code == 201
    session = api.factory.sessions[0]
    session.duration_seconds = 42.5

    body = _week(api, "2000-01-01", today.isoformat())
    items = [item for day in body["days"] for item in day["items"]]

    live = next(item for item in items if item["id"] == started.json()["id"])
    assert live["status"] == "recording"
    assert live["duration_seconds"] == 42.5


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-10-18", "to": "2026-10-12"},
        {"from": "2026-10-12"},
        {"to": "2026-10-12"},
    ],
)
def test_an_invalid_range_is_422(api: Api, params: dict[str, str]) -> None:
    response = api.client.get("/sessions", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_date_range"


def test_a_malformed_date_is_422(api: Api) -> None:
    response = api.client.get("/sessions", params={"from": "monday", "to": "2026-10-18"})

    assert response.status_code == 422


def test_without_dates_the_paged_list_is_unchanged(api: Api) -> None:
    session_id = _meeting(api, _local(2026, 10, 13, 10), 900)

    body = api.client.get("/sessions").json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == session_id


def test_the_database_backend_lists_the_same_days(api: Api, tmp_path: Path) -> None:
    database = Database(tmp_path / "vozata.db")
    store = SqliteSessionRepository(database, tmp_path / "db-recordings")
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, store=store, storage=StorageInfo("sqlite", database.path)
    )
    api.store = store  # type: ignore[assignment]
    first = _meeting(api, _local(2026, 10, 13, 10), 900)
    second = _meeting(api, _local(2026, 10, 13, 11), 300)

    body = _week(api)

    assert body["storage"] == "sqlite"
    assert [item["id"] for item in body["days"][0]["items"]] == [second, first]
    assert body["total_seconds"] == 1200
    database.close()


# The grouping itself, with explicit time zones


def test_local_bounds_cover_whole_days_in_the_zone() -> None:
    start, end = local_bounds(date(2026, 10, 12), date(2026, 10, 18), BRT)

    assert start == datetime(2026, 10, 12, tzinfo=BRT)
    assert end == datetime(2026, 10, 19, tzinfo=BRT)
    local_start, _ = local_bounds(date(2026, 10, 12), date(2026, 10, 12))
    assert local_start.tzinfo is not None


def test_the_day_follows_the_zone_not_the_offset_it_was_recorded_with() -> None:
    summary = {"id": "20261016_023000", "started_at": "2026-10-16T02:30:00+00:00"}

    assert local_day(summary, BRT) == date(2026, 10, 15)  # 23:30 in Brasília
    assert local_day(summary, UTC) == date(2026, 10, 16)
    assert local_day({"id": "imported", "started_at": None}) is None


def test_group_by_day_sums_missing_durations_as_zero_and_skips_undated_sessions() -> None:
    summaries = [
        {"id": "20261016_100000", "started_at": None, "duration_seconds": None},
        {"id": "20261016_090000", "started_at": None, "duration_seconds": 30.0},
        {"id": "imported", "started_at": None, "duration_seconds": 99.0},
    ]

    grouped = group_by_day(summaries, BRT)

    assert grouped["total_seconds"] == 30.0
    assert len(grouped["days"]) == 1
    assert [item["id"] for item in grouped["days"][0]["items"]] == [
        "20261016_100000",
        "20261016_090000",
    ]
