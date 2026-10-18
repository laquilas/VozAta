"""When a session started, and the sessions of a time range (phase 36)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from vozata.storage.session_range import newest_in_range, session_start

BRT = timezone(timedelta(hours=-3))


def test_started_at_wins_over_the_id() -> None:
    start = session_start("20261015_202358", "2026-10-15T23:30:00-03:00")

    assert start == datetime(2026, 10, 16, 2, 30, tzinfo=UTC)
    assert start is not None and start.tzinfo is not None


def test_a_naive_started_at_is_local_time() -> None:
    assert session_start("20261015_202358", "2026-10-15T20:00:00") == (
        datetime(2026, 10, 15, 20, 0).astimezone()
    )


def test_a_missing_or_unreadable_started_at_falls_back_to_the_id() -> None:
    local = datetime(2026, 10, 15, 20, 23, 58).astimezone()

    assert session_start("20261015_202358", None) == local
    assert session_start("20261015_202358_2", "yesterday") == local
    assert session_start("20261015_202358", 42) == local


def test_without_a_readable_time_there_is_no_start() -> None:
    assert session_start("imported", None) is None


def test_newest_in_range_is_half_open_and_sorted_newest_first() -> None:
    sessions = [
        ("a", "2026-10-12T00:00:00+00:00"),
        ("b", "2026-10-12T05:00:00-03:00"),  # 08:00 UTC
        ("c", "2026-10-13T00:00:00+00:00"),  # the end: excluded
        ("bad", None),
    ]

    found = newest_in_range(
        sessions, datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 13, tzinfo=UTC)
    )

    assert found == ["b", "a"]
    assert newest_in_range([], datetime(2026, 1, 1, tzinfo=BRT), datetime.now(BRT)) == []
