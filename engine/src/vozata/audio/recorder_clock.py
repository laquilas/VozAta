"""The session clock of a recording made by the recorder process (phase 61).

Session time is the recording's time: wall time since the recorder's `started_at`, the same
timeline as the frames of its files. Once the recording stopped, `stop_at(duration)` freezes it
at the recording's real length, so the engine never counts the time it took to notice.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime


class RecorderClock:
    def __init__(
        self,
        started_at: datetime,
        wall: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._started_at = started_at
        self._wall = wall
        self._stopped: float | None = None

    def start(self) -> None:
        """The recorder started the clock; nothing to do."""

    def now(self) -> float:
        if self._stopped is not None:
            return self._stopped
        return max(0.0, (self._wall() - self._started_at).total_seconds())

    def stop_at(self, seconds: float) -> None:
        self._stopped = seconds
