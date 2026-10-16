"""One long-lived thread for every PortAudio call of a session.

WASAPI binds PortAudio's host state to the thread that initialized it (COM): a stream opened from
another thread fails with "Unanticipated host error" (-9999), and once that thread exits, later
opens fail too. A `PortAudioThread` creates the `PyAudio` instance and runs device lookups, opens
and `terminate()` on its own thread; callers wait at most `timeout` seconds per call, because a
driver can hang.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

PORTAUDIO_TIMEOUT = 20.0
CLOSE_TIMEOUT = 5.0  # the thread may still be stuck in a hung open


def _pyaudio() -> Any:  # pragma: no cover - hardware
    import pyaudiowpatch

    return pyaudiowpatch.PyAudio()


class PortAudioThread:
    def __init__(
        self, factory: Callable[[], Any] = _pyaudio, timeout: float = PORTAUDIO_TIMEOUT
    ) -> None:
        self.timeout = timeout
        self._jobs: queue.Queue[tuple[Callable[[], Any], list, threading.Event] | None] = (
            queue.Queue()
        )
        self._thread = threading.Thread(target=self._serve, name="portaudio", daemon=True)
        self._thread.start()
        self.pa: Any = self.call(factory)

    def call[T](self, function: Callable[[], T], timeout: float | None = None) -> T:
        """Run `function` on the PortAudio thread; `TimeoutError` if it takes too long."""
        limit = self.timeout if timeout is None else timeout
        result: list[tuple[bool, Any]] = []
        done = threading.Event()
        self._jobs.put((function, result, done))
        if not done.wait(limit):
            raise TimeoutError(f"PortAudio did not answer within {limit} s")
        ok, value = result[0]
        if not ok:
            raise value
        return value

    def close(self) -> None:
        """Terminate PortAudio (once) and end the thread."""
        if self.pa is None:
            return
        pa, self.pa = self.pa, None
        try:
            self.call(pa.terminate, CLOSE_TIMEOUT)
        finally:
            self._jobs.put(None)

    def _serve(self) -> None:
        while (job := self._jobs.get()) is not None:
            function, result, done = job
            try:
                result.append((True, function()))
            except Exception as error:
                result.append((False, error))
            done.set()
