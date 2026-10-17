from __future__ import annotations

import threading

import pytest

from vozata.heartbeat import Heartbeat


def test_beats_periodically_until_stopped() -> None:
    beats: list[int] = []
    three = threading.Event()

    def beat() -> None:
        beats.append(1)
        if len(beats) >= 3:
            three.set()

    heartbeat = Heartbeat(0.01, beat)
    heartbeat.start()
    assert three.wait(5)
    heartbeat.stop()
    count = len(beats)
    threading.Event().wait(0.05)

    assert count >= 3
    assert len(beats) == count  # no beat after stop


def test_a_failing_beat_is_logged_and_the_next_one_runs(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[int] = []
    second = threading.Event()

    def beat() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        second.set()

    heartbeat = Heartbeat(0.01, beat, name="autosave")
    heartbeat.start()
    assert second.wait(5)
    heartbeat.stop()

    assert "Heartbeat autosave failed" in caplog.text


def test_stop_before_start_is_a_no_op_and_start_twice_raises() -> None:
    heartbeat = Heartbeat(1, lambda: None)
    heartbeat.stop()

    other = Heartbeat(60, lambda: None)
    other.start()
    with pytest.raises(RuntimeError):
        other.start()
    other.stop()


def test_stop_from_the_beat_itself_does_not_deadlock() -> None:
    done = threading.Event()
    holder: list[Heartbeat] = []

    def beat() -> None:
        holder[0].stop()
        done.set()

    heartbeat = Heartbeat(0.01, beat)
    holder.append(heartbeat)
    heartbeat.start()

    assert done.wait(5)


@pytest.mark.parametrize("interval", [0, -1])
def test_the_interval_must_be_positive(interval: float) -> None:
    with pytest.raises(ValueError):
        Heartbeat(interval, lambda: None)
