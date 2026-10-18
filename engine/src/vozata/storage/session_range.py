"""Sessions in a time range (phase 36), shared by the storage backends."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def session_start(session_id: str, started_at: object) -> datetime | None:
    """When a session started: `started_at` (ISO 8601), else the local time in its id
    (`YYYYMMDD_HHMMSS`); None when neither can be read. Naive times are local time."""
    if isinstance(started_at, str):
        try:
            return datetime.fromisoformat(started_at).astimezone()
        except ValueError:
            pass
    try:
        return datetime.strptime(session_id[:15], "%Y%m%d_%H%M%S").astimezone()
    except ValueError:
        return None


def newest_in_range(
    sessions: Iterable[tuple[str, object]], start: datetime, end: datetime
) -> list[str]:
    """Ids of `(id, started_at)` pairs that started in `[start, end)`, newest first."""
    found = []
    for session_id, started_at in sessions:
        begun = session_start(session_id, started_at)
        if begun is not None and start <= begun < end:
            found.append((begun, session_id))
    found.sort(reverse=True)
    return [session_id for _, session_id in found]
