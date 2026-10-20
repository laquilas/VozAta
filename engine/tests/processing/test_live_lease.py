from __future__ import annotations

import threading

import pytest

from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.live_lease import LiveGpuLease, LiveModelTurn

SPEECH = GpuUsage(speech=True, speakers=False, llm=True)
SPEAKERS = GpuUsage(speech=False, speakers=True, llm=False)
NONE = GpuUsage(speech=False, speakers=False, llm=True)


@pytest.mark.parametrize("usage", [SPEECH, SPEAKERS])
def test_hold_takes_the_live_priority_once_until_release(usage: GpuUsage) -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, usage)
    assert not gate.priority_held

    lease.hold()
    lease.hold()  # the second model load shares the hold
    assert gate.priority_held

    lease.release()
    assert not gate.priority_held


@pytest.mark.parametrize(("gate", "usage"), [(GpuGate(), NONE), (None, SPEECH), (GpuGate(), None)])
def test_nothing_is_held_without_a_gate_or_a_live_gpu_model(
    gate: GpuGate | None, usage: GpuUsage | None
) -> None:
    lease = LiveGpuLease(gate, usage)

    lease.hold()

    assert gate is None or not gate.priority_held
    lease.release()  # harmless


def test_a_hold_after_release_does_nothing() -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, SPEECH)

    lease.release()  # Stop before the model load ended
    lease.hold()

    assert not gate.priority_held


def test_the_turn_waits_for_the_last_stopped_session_and_warns_while_it_does(
    caplog: pytest.LogCaptureFixture,
) -> None:
    turn = LiveModelTurn(warn_every=0.01)
    turn.wait()  # nothing stopped yet: no wait
    closed = threading.Event()
    turn.stopping(closed)
    waiting = threading.Thread(target=turn.wait)

    waiting.start()
    threading.Event().wait(0.1)
    assert waiting.is_alive()
    closed.set()
    waiting.join(5)

    assert not waiting.is_alive()
    assert "still waiting for the previous recording's live models to close" in caplog.text
