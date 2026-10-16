"""Session clock: seconds since the session started (injectable time source)."""

from __future__ import annotations

import time
from collections.abc import Callable


class SessionClock:
    def __init__(self, time_source: Callable[[], float] = time.monotonic) -> None:
        self._time = time_source
        self._started_at: float | None = None

    def start(self) -> None:
        self._started_at = self._time()

    def now(self) -> float:
        if self._started_at is None:
            raise RuntimeError("SessionClock.now() called before start()")
        return self._time() - self._started_at
