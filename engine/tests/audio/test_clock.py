from __future__ import annotations

import pytest

from vozata.audio.clock import SessionClock


class FakeTime:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_now_counts_seconds_since_start() -> None:
    time = FakeTime()
    clock = SessionClock(time)

    clock.start()
    time.value = 102.5

    assert clock.now() == pytest.approx(2.5)


def test_now_before_start_raises() -> None:
    with pytest.raises(RuntimeError):
        SessionClock(FakeTime()).now()


def test_default_time_source_is_monotonic() -> None:
    clock = SessionClock()
    clock.start()

    assert 0.0 <= clock.now() < 5.0
