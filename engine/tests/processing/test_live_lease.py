from __future__ import annotations

import pytest

from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.live_lease import LiveGpuLease

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
