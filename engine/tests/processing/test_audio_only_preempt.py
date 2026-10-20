"""Regression pin (phase 41 on phase 40 code): the queued `transcribe` step of an audio-only
meeting is pre-empted by a live recording (a GPU priority holder), shows `paused`, and later
resumes from where it stopped instead of starting over."""

from __future__ import annotations

import threading
from pathlib import Path

from tests.processing.test_queue import TIMEOUT, _job, _make, _step
from tests.transcription.test_offline import _Rig, _said, _track
from vozata.domain import Channel
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuGate, GpuUser
from vozata.processing.job import StepKind
from vozata.processing.session_job import Progress


def test_a_preempted_audio_only_transcription_resumes_where_it_stopped(tmp_path: Path) -> None:
    rig = _Rig(  # no raw transcript yet: recorded with live transcription off
        tmp_path,
        {Channel.MIC: _track(30, (0.0, 9.0), (20.0, 25.0)), Channel.SYSTEM: _track(30)},
        [
            _said("Hello", 0.5, 1.0),
            _said("Hello there.", 0.5, 9.0),
            _said("Later", 0.5, 1.0),
            _said("Later on.", 0.5, 4.5),
        ],
    )
    gate = GpuGate()
    queue, recorder = _make(gate=gate)
    first_block = threading.Event()
    attempts: list[int] = []  # the audio reads already made when each attempt started

    def transcribe(token: CancelToken, progress: Progress) -> None:
        attempts.append(len(rig.audio.reads))

        def report(fraction: float) -> None:
            progress(fraction)
            if len(attempts) == 1:  # hold the first attempt after its first block until pre-empted
                first_block.set()
                while not token.cancelled:
                    threading.Event().wait(0.005)

        rig.offline.run(rig.session_id, token, report)

    queue.enqueue(_job("a", [_step(StepKind.TRANSCRIBE, gpu=True, run=transcribe)]))
    queue.start()
    assert first_block.wait(TIMEOUT)
    with gate.priority(GpuUser.LIVE):  # a live recording starts
        for _ in range(int(TIMEOUT / 0.005)):
            if any(state.state == "paused" for state in recorder.of("a")):
                break
            threading.Event().wait(0.005)
    assert queue.wait_idle(TIMEOUT)
    queue.stop()

    assert [s.text for s in rig.stored()] == ["Hello there.", "Later on."]  # nothing twice
    assert len(attempts) == 2
    resumed = rig.audio.reads[attempts[1] :]
    assert min(start for channel, start, _ in resumed if channel is Channel.MIC) >= 9000
    states = [state.state for state in recorder.of("a")]
    paused = states.index("paused")
    assert states[paused + 1] == "running" and states[-1] == "done"
