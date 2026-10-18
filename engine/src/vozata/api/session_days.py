"""Meetings grouped by local day (phase 36): `GET /sessions?from=&to=`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from vozata.storage.session_range import session_start

# Before any recording: `has_earlier` looks from here up to the start of the range.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def local_bounds(first: date, last: date, tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """`[first 00:00, last + 1 day 00:00)` in `tz` (default: the local time zone, DST aware)."""
    start = datetime.combine(first, time())
    end = datetime.combine(last + timedelta(days=1), time())
    if tz is None:
        return start.astimezone(), end.astimezone()
    return start.replace(tzinfo=tz), end.replace(tzinfo=tz)


def local_day(summary: dict[str, Any], tz: tzinfo | None = None) -> date | None:
    """The day a meeting started on in `tz` (default: local); a meeting crossing midnight stays
    on its start day."""
    begun = session_start(summary["id"], summary.get("started_at"))
    return None if begun is None else begun.astimezone(tz).date()


def group_by_day(summaries: Sequence[dict[str, Any]], tz: tzinfo | None = None) -> dict[str, Any]:
    """`{days: [{date, total_seconds, items}], total_seconds}`, days newest first; `summaries`
    keep their order inside a day (newest first from `list_range`)."""
    days: dict[date, list[dict[str, Any]]] = {}
    for summary in summaries:
        day = local_day(summary, tz)
        if day is not None:
            days.setdefault(day, []).append(summary)
    grouped = [
        {"date": day.isoformat(), "total_seconds": _total(items), "items": items}
        for day, items in sorted(days.items(), reverse=True)
    ]
    return {"days": grouped, "total_seconds": sum(day["total_seconds"] for day in grouped)}


def _total(items: Sequence[dict[str, Any]]) -> float:
    return float(sum(item.get("duration_seconds") or 0.0 for item in items))
