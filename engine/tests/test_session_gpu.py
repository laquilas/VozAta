"""A live session's hold on the GPU gate and its skipped model loads (phase 40)."""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

from tests.fakes import FakeEmbedder
from tests.test_session import SETTINGS, _Rig, _voice, _wait_for
from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.live_lease import LiveModelTurn

LIVE = dataclasses.replace(SETTINGS, chunk_seconds=3.0)
POST_SPEAKERS_ON_GPU = GpuUsage(speech=False, speakers=True, llm=False)
LIVE_SPEAKERS_ON_GPU = GpuUsage(speech=False, speakers=True, llm=False, live_speakers=True)
SPEECH_ON_GPU = GpuUsage(speech=True, speakers=False, llm=False)


def test_external_speech_with_post_session_speakers_on_the_gpu_never_holds_the_gate(
    tmp_path: Path,
) -> None:
    gate = GpuGate()
    rig = _Rig(tmp_path, gate=gate, gpu_usage=POST_SPEAKERS_ON_GPU, with_minutes=False)
    rig.session.start()
    _wait_for(lambda: "transcriber.load" in rig.log.entries)

    assert not gate.priority_held  # the queue keeps its GPU work while this records
    closed = rig.session.stop_capture()
    assert closed.wait(5)
    assert not gate.priority_held


def test_live_speakers_on_the_gpu_hold_the_gate_until_the_pipeline_closed(
    tmp_path: Path,
) -> None:
    gate = GpuGate()
    rig = _Rig(
        tmp_path,
        settings=LIVE,
        gate=gate,
        gpu_usage=LIVE_SPEAKERS_ON_GPU,
        embedder_factory=FakeEmbedder,
        with_minutes=False,
    )
    rig.session.start()

    _wait_for(lambda: gate.priority_held)
    closed = rig.session.stop_capture()
    assert closed.wait(5)
    assert not gate.priority_held


def test_a_session_stopped_while_waiting_for_its_turn_never_loads_nor_holds(
    tmp_path: Path,
) -> None:
    turn = LiveModelTurn()
    previous = threading.Event()
    turn.stopping(previous)  # the previous recording's models are still closing
    gate = GpuGate()
    rig = _Rig(tmp_path, gate=gate, gpu_usage=SPEECH_ON_GPU, live_models=turn)
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)
    threading.Event().wait(0.1)  # the load waits for its turn

    closed = rig.session.stop_capture()
    previous.set()

    assert closed.wait(5)
    assert "transcriber.load" not in rig.log.entries
    assert not gate.priority_held
    assert rig.observer.of("error") == []  # a skip, not a model failure
    assert rig.session._pipeline.transcriber is None
