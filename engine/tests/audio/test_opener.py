from __future__ import annotations

import threading

import numpy as np
import pytest

from tests.fakes import FakeAudioSource
from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout


def _ignore(samples: np.ndarray, at: float) -> None:
    pass


class _SlowSource(FakeAudioSource):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.returned = threading.Event()

    def start(self, on_samples) -> None:  # type: ignore[no-untyped-def]
        self.release.wait(10)
        super().start(on_samples)
        self.returned.set()


class _BrokenSource(FakeAudioSource):
    def start(self, on_samples) -> None:  # type: ignore[no-untyped-def]
        raise OSError("Invalid device")


def test_a_source_that_opens_in_time_is_started_with_the_callback() -> None:
    received: list[float] = []
    source = FakeAudioSource([(np.zeros(4, np.float32), 1.5)])

    open_with_timeout(source, lambda samples, at: received.append(at), 1.0, lambda: True)

    assert source.started and not source.stopped
    assert received == [1.5]


def test_the_source_error_is_raised_to_the_caller() -> None:
    with pytest.raises(OSError, match="Invalid device"):
        open_with_timeout(_BrokenSource(), _ignore, 1.0, lambda: True)


def test_a_hanging_source_times_out_and_is_stopped_once_it_opens_late() -> None:
    source = _SlowSource()
    wanted = True

    with pytest.raises(SourceOpenTimeoutError):
        open_with_timeout(source, _ignore, 0.05, lambda: wanted)

    wanted = False
    source.release.set()
    assert source.returned.wait(5)
    for _ in range(100):
        if source.stopped:
            break
        threading.Event().wait(0.01)
    assert source.stopped
