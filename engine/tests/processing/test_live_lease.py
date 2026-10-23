from __future__ import annotations

import threading

import pytest

from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.live_lease import LiveGpuLease, LiveModelTurn

SPEECH = GpuUsage(speech=True, speakers=False, llm=True)
LIVE_SPEAKERS = GpuUsage(speech=False, speakers=True, llm=False, live_speakers=True)
POST_SPEAKERS = GpuUsage(speech=False, speakers=True, llm=False)  # post-session pyannote only
NONE = GpuUsage(speech=False, speakers=False, llm=True)


def test_the_speech_hold_takes_the_live_priority_once_until_release() -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, SPEECH)
    assert not gate.priority_held

    lease.hold_speech()
    lease.hold_speakers()  # a CPU embedder: no hold of its own
    lease.hold_speech()  # a second load shares the hold
    assert gate.priority_held

    lease.release()
    assert not gate.priority_held


def test_the_live_speaker_embedder_on_the_gpu_holds_the_gate() -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, LIVE_SPEAKERS)

    lease.hold_speech()  # external or CPU speech: no hold
    assert not gate.priority_held
    lease.hold_speakers()
    assert gate.priority_held

    lease.release()
    assert not gate.priority_held


def test_post_session_diarization_on_the_gpu_does_not_hold_the_gate() -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, POST_SPEAKERS)

    lease.hold_speech()
    lease.hold_speakers()

    assert not gate.priority_held


@pytest.mark.parametrize(("gate", "usage"), [(GpuGate(), NONE), (None, SPEECH), (GpuGate(), None)])
def test_nothing_is_held_without_a_gate_or_a_live_gpu_model(
    gate: GpuGate | None, usage: GpuUsage | None
) -> None:
    lease = LiveGpuLease(gate, usage)

    lease.hold_speech()
    lease.hold_speakers()

    assert gate is None or not gate.priority_held
    lease.release()  # harmless


def test_a_fallback_from_the_worker_holds_the_gate_only_when_whisper_would_use_the_gpu() -> None:
    gate = GpuGate()
    on_worker = LiveGpuLease(gate, GpuUsage(False, False, False, speech_fallback=True))
    on_cpu = LiveGpuLease(gate, NONE)

    on_worker.hold_speech()  # the worker's model: nothing here
    on_cpu.hold_speech_fallback()
    assert not gate.priority_held

    on_worker.hold_speech_fallback()
    assert gate.priority_held
    on_worker.release()
    assert not gate.priority_held


def test_a_hold_after_release_does_nothing() -> None:
    gate = GpuGate()
    lease = LiveGpuLease(gate, SPEECH)

    lease.release()  # Stop before the model load ended
    lease.hold_speech()

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
