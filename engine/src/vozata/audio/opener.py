"""Open an `AudioSource` without blocking forever (a WASAPI open can hang in the driver)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from vozata.ports import AudioSource


class SourceOpenTimeoutError(TimeoutError):
    """The source did not start within the timeout; it is released if it opens later."""


def open_with_timeout(
    source: AudioSource,
    on_samples: Callable[[np.ndarray, float], None],
    timeout: float,
    still_wanted: Callable[[], bool],
) -> None:
    """Start `source` on a helper thread and wait at most `timeout` seconds.

    Raises `SourceOpenTimeoutError` on timeout, or re-raises the source's own error. A source that
    finishes opening after the caller gave up (`still_wanted()` is False) is stopped at once.
    """
    failure: list[Exception] = []

    def run() -> None:
        try:
            source.start(on_samples)
        except Exception as error:
            failure.append(error)
            return
        if not still_wanted():
            source.stop()

    thread = threading.Thread(target=run, name="open-audio-source", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise SourceOpenTimeoutError(f"Audio source did not open within {timeout} s")
    if failure:
        raise failure[0]
