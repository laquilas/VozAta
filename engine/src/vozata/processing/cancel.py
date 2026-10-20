"""Cooperative cancellation for one background processing step."""

from __future__ import annotations

import threading
from collections.abc import Callable


class StepCancelled(Exception):
    """Raised when a processing step is stopped because its token was cancelled."""


class CancelToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Mark the token cancelled and run the registered callbacks once, outside the lock."""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback()

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register `callback` (runs now if cancelled); returns an unregister function."""
        with self._lock:
            if not self._cancelled:
                self._callbacks.append(callback)

                def unregister() -> None:
                    with self._lock:
                        if callback in self._callbacks:
                            self._callbacks.remove(callback)

                return unregister
        callback()
        return lambda: None

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise StepCancelled
