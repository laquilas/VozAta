"""A periodic callback on a daemon thread (`session.json` autosave, phase 17)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

_log = logging.getLogger(__name__)


class Heartbeat:
    """Call `beat` every `interval` seconds from `start()` until `stop()`.

    A failing beat is logged and the next one still runs: autosave must never end a recording.
    """

    def __init__(self, interval: float, beat: Callable[[], None], name: str = "heartbeat") -> None:
        if interval <= 0:
            raise ValueError("The heartbeat interval must be positive")
        self._interval = interval
        self._beat = beat
        self._name = name
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("A heartbeat can only be started once")
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop beating and wait for a beat in progress (no-op before `start()`)."""
        self._stopped.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _run(self) -> None:
        while not self._stopped.wait(self._interval):
            try:
                self._beat()
            except Exception:
                _log.exception("Heartbeat %s failed", self._name)
