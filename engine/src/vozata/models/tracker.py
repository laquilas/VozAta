"""Model download progress, turned into throttled `download_progress` states (phase 42)."""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from vozata.domain import ModelKind

DownloadPhase = Literal["running", "done", "failed"]


@dataclass(frozen=True)
class DownloadState:
    """One download's progress; `total_bytes` is None when the size is unknown."""

    kind: ModelKind
    model: str
    downloaded_bytes: int
    total_bytes: int | None
    state: DownloadPhase
    reason: str | None = None  # why a `failed` download failed

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "model": self.model,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "state": self.state,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


class DownloadHandle:
    """Reports one download's progress to its tracker; calls after `done`/`failed` are ignored."""

    def __init__(self, tracker: DownloadTracker, key: int) -> None:
        self._tracker = tracker
        self._key = key

    def advance(self, n: int) -> None:
        self._tracker._advance(self._key, n)

    def done(self) -> None:
        self._tracker._finish(self._key, "done", None)

    def failed(self, reason: str) -> None:
        self._tracker._finish(self._key, "failed", reason)


class DownloadTracker:
    """Thread-safe registry of the downloads in progress.

    Publishes every state change (start, done, failed) and, per download, a `running` state at
    most every `interval` seconds. `publish` runs under the tracker's lock so states never arrive
    out of order: it must be quick (e.g. hand the state to an event queue).
    """

    def __init__(
        self,
        publish: Callable[[DownloadState], None],
        clock: Callable[[], float] = time.monotonic,
        interval: float = 0.5,
    ) -> None:
        self._publish = publish
        self._clock = clock
        self._interval = interval
        self._lock = threading.RLock()
        self._keys = itertools.count()
        self._states: dict[int, DownloadState] = {}
        self._published_at: dict[int, float] = {}

    def start(self, kind: ModelKind, model: str, total: int | None) -> DownloadHandle:
        with self._lock:
            key = next(self._keys)
            state = DownloadState(kind, model, 0, total, "running")
            self._states[key] = state
            self._emit(key, state)
        return DownloadHandle(self, key)

    def running(self) -> list[DownloadState]:
        """The downloads in progress (the snapshot a newly connected client receives)."""
        with self._lock:
            return list(self._states.values())

    def _advance(self, key: int, n: int) -> None:
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return
            state = replace(state, downloaded_bytes=state.downloaded_bytes + n)
            self._states[key] = state
            if self._clock() - self._published_at[key] >= self._interval:
                self._emit(key, state)

    def _finish(self, key: int, phase: DownloadPhase, reason: str | None) -> None:
        with self._lock:
            state = self._states.pop(key, None)
            if state is None:
                return
            self._published_at.pop(key, None)
            self._publish(replace(state, state=phase, reason=reason))

    def _emit(self, key: int, state: DownloadState) -> None:
        self._published_at[key] = self._clock()
        self._publish(state)
