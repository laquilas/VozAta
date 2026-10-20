import threading

from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.gpu_gate import GpuGate, GpuUser
from vozata.processing.job import AbortJob, ProcessingJob, Step, StepKind
from vozata.processing.queue import ProcessingQueue, ProcessingState

TIMEOUT = 3.0


class Recorder:
    def __init__(self) -> None:
        self.states: list[ProcessingState] = []
        self._lock = threading.Lock()

    def __call__(self, state: ProcessingState) -> None:
        with self._lock:
            self.states.append(state)

    def of(self, session_id: str) -> list[ProcessingState]:
        with self._lock:
            return [s for s in self.states if s.session_id == session_id]


def _step(kind=StepKind.INDEX, weight=1.0, gpu=False, run=None) -> Step:
    return Step(kind=kind, weight=weight, gpu=gpu, run=run or (lambda token, progress: None))


def _make(clock=None, interval=1.0, gate=None):
    recorder = Recorder()
    kwargs = {"clock": clock} if clock else {}
    queue = ProcessingQueue(gate or GpuGate(), recorder, progress_interval=interval, **kwargs)
    return queue, recorder


def _job(sid, steps, on_finished=lambda: None, before=lambda: None) -> ProcessingJob:
    return ProcessingJob(sid, tuple(steps), on_finished=on_finished, before=before)


def test_jobs_run_one_at_a_time_in_enqueue_order():
    queue, _ = _make()
    log: list[str] = []
    first_in = threading.Event()
    release = threading.Event()

    def first(token, progress):
        log.append("a-start")
        first_in.set()
        release.wait(TIMEOUT)
        log.append("a-end")

    def second(token, progress):
        log.append("b")

    queue.enqueue(_job("a", [_step(run=first)]))
    queue.enqueue(_job("b", [_step(run=second)]))
    queue.start()
    assert first_in.wait(TIMEOUT)
    assert log == ["a-start"]
    release.set()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert log == ["a-start", "a-end", "b"]


def test_queued_states_carry_positions_and_update_when_one_starts():
    queue, rec = _make()
    gate_in = threading.Event()
    release = threading.Event()

    def block(token, progress):
        gate_in.set()
        release.wait(TIMEOUT)

    queue.enqueue(_job("a", [_step(run=block)]))
    queue.enqueue(_job("b", [_step()]))
    queue.enqueue(_job("c", [_step()]))
    assert [s.position for s in (queue.state("a"), queue.state("b"), queue.state("c"))] == [
        1,
        2,
        3,
    ]
    queue.start()
    assert gate_in.wait(TIMEOUT)
    assert queue.state("b").position == 1
    assert queue.state("c").position == 2
    assert queue.state("b").to_payload() == {
        "state": "queued",
        "percent": 0,
        "step": None,
        "position": 1,
    }
    release.set()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert [s.position for s in rec.of("c") if s.state == "queued"] == [3, 2, 1]


def test_percent_is_monotonic_and_reaches_100_with_done_last():
    queue, rec = _make(interval=0.0)
    finished: list[int] = []

    def half(token, progress):
        progress(0.5)
        progress(0.25)  # a lower fraction must not lower the percent
        progress(1.0)

    queue.enqueue(
        _job(
            "a",
            [
                _step(StepKind.TRANSCRIBE, 3.0, run=half),
                _step(StepKind.MIX, 1.0),
                _step(StepKind.INDEX, 1.0),
            ],
            on_finished=lambda: finished.append(len(rec.of("a"))),
        )
    )
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    states = rec.of("a")
    percents = [s.percent for s in states]
    assert percents == sorted(percents)
    assert states[-1].state == "done" and states[-1].percent == 100
    assert finished == [len(states)]  # on_finished ran after the done state
    assert any(s.percent == 60 for s in states)
    assert queue.state("a") is None


def test_cancelled_gpu_step_is_paused_then_redone_and_done_once():
    gate = GpuGate()
    queue, rec = _make(gate=gate)
    effects: list[str] = []
    attempts = {"n": 0}
    started = threading.Event()
    tokens: list[CancelToken] = []

    def first(token, progress):
        effects.append("first")

    def second(token, progress):
        tokens.append(token)
        attempts["n"] += 1
        if attempts["n"] == 1:
            started.set()
            while not token.cancelled:
                threading.Event().wait(0.005)
            raise StepCancelled
        effects.append("second")

    queue.enqueue(
        _job(
            "a",
            [_step(gpu=True, run=first), _step(gpu=True, run=second)],
            on_finished=lambda: effects.append("fin"),
        )
    )
    queue.start()
    assert started.wait(TIMEOUT)
    with gate.priority(GpuUser.LIVE):
        pass
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert effects == ["first", "second", "fin"]
    assert attempts["n"] == 2
    assert tokens[0] is not tokens[1] and tokens[0].cancelled and not tokens[1].cancelled
    kinds = [s.state for s in rec.of("a")]
    assert "paused" in kinds
    assert kinds.index("paused") < len(kinds) - 1 and kinds[-1] == "done"
    assert kinds[kinds.index("paused") + 1] == "running"


def test_step_finishing_as_cancel_lands_is_not_run_again():
    queue, _ = _make()
    runs = {"n": 0}

    def run(token, progress):
        runs["n"] += 1
        token.cancel()  # the cancel arrives, but the step still completes

    queue.enqueue(_job("a", [_step(gpu=True, run=run)]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert runs["n"] == 1


def test_failing_step_does_not_stop_the_job_or_the_queue():
    queue, rec = _make()
    ran: list[str] = []

    def boom(token, progress):
        raise RuntimeError("x")

    queue.enqueue(_job("a", [_step(run=boom), _step(run=lambda t, p: ran.append("a2"))]))
    queue.enqueue(_job("b", [_step(run=lambda t, p: ran.append("b"))]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert ran == ["a2", "b"]
    assert rec.of("a")[-1].state == "done"


def test_failing_on_finished_publishes_failed_and_removes_the_job():
    queue, rec = _make()

    def bad():
        raise RuntimeError("nope")

    queue.enqueue(_job("a", [_step()], on_finished=bad))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert [s.state for s in rec.of("a")][-2:] == ["done", "failed"]
    assert queue.contains("a") is False


def test_failing_before_hook_is_logged_and_the_job_still_runs():
    queue, _ = _make()
    ran: list[str] = []

    def bad():
        raise RuntimeError("no sink")

    queue.enqueue(_job("a", [_step(run=lambda t, p: ran.append("x"))], before=bad))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert ran == ["x"]


def test_non_gpu_steps_ignore_the_gate():
    gate = GpuGate()
    queue, _ = _make(gate=gate)
    ran = threading.Event()
    queue.enqueue(_job("a", [_step(gpu=False, run=lambda t, p: ran.set())]))
    with gate.priority(GpuUser.LIVE):
        queue.start()
        assert ran.wait(TIMEOUT)
    assert queue.wait_idle(TIMEOUT)
    queue.stop()


def test_gpu_step_waits_for_priority_user_and_shows_paused():
    gate = GpuGate()
    queue, rec = _make(gate=gate)
    ran = threading.Event()
    queue.enqueue(_job("a", [_step(gpu=True, run=lambda t, p: ran.set())]))
    with gate.priority(GpuUser.ASK):
        queue.start()
        for _ in range(400):
            if queue.state("a") and queue.state("a").state == "paused":
                break
            threading.Event().wait(0.005)
        assert queue.state("a").state == "paused"
        assert not ran.is_set()
    assert ran.wait(TIMEOUT)
    assert queue.wait_idle(TIMEOUT)
    queue.stop()


def test_progress_is_throttled_to_the_interval():
    now = {"t": 0.0}
    queue, rec = _make(clock=lambda: now["t"], interval=1.0)

    def run(token, progress):
        progress(0.1)  # t=0: too soon after the start
        now["t"] = 1.0
        progress(0.3)  # published
        now["t"] = 1.5
        progress(0.6)  # throttled
        now["t"] = 2.5
        progress(0.9)  # published

    queue.enqueue(_job("a", [_step(StepKind.MINUTES, 1.0, run=run), _step(StepKind.INDEX, 1.0)]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    running = [s.percent for s in rec.of("a") if s.state == "running"]
    assert 15 in running and 45 in running
    assert 5 not in running and 30 not in running


def test_pending_lists_running_then_queued():
    queue, _ = _make()
    inside = threading.Event()
    release = threading.Event()

    def block(token, progress):
        inside.set()
        release.wait(TIMEOUT)

    queue.enqueue(_job("a", [_step(run=block)]))
    queue.enqueue(_job("b", [_step()]))
    queue.enqueue(_job("c", [_step()]))
    queue.start()
    assert inside.wait(TIMEOUT)
    assert [(s.session_id, s.state) for s in queue.pending()] == [
        ("a", "running"),
        ("b", "queued"),
        ("c", "queued"),
    ]
    assert queue.contains("b") and not queue.contains("zzz")
    release.set()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert queue.pending() == []


def test_duplicate_enqueue_is_ignored_and_payload_omits_position_when_running():
    queue, _ = _make()
    queue.enqueue(_job("a", [_step(StepKind.FINALIZE), _step(StepKind.DIARIZE)]))
    queue.enqueue(_job("a", [_step()]))
    assert len(queue.pending()) == 1
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    state = ProcessingState("a", "running", 10, StepKind.DIARIZE, None)
    assert state.to_payload() == {"state": "running", "percent": 10, "step": "diarize"}


def test_wait_idle_times_out_while_work_is_pending():
    queue, _ = _make()
    queue.enqueue(_job("a", [_step()]))
    assert queue.wait_idle(0.05) is False  # worker not started
    queue.start()
    queue.start()  # second start is a no-op
    assert queue.wait_idle(TIMEOUT)
    queue.stop()


def test_each_step_publishes_its_kind_before_it_finishes():
    queue, rec = _make(interval=0.0)
    seen: list[StepKind | None] = []

    def second(token, progress):
        seen.append(queue.state("a").step)

    queue.enqueue(_job("a", [_step(StepKind.ACTION_ITEMS), _step(StepKind.INDEX, run=second)]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert seen == [StepKind.INDEX]


def test_publish_failure_does_not_kill_the_worker():
    calls = {"n": 0}
    done: list[str] = []

    def publish(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("socket gone")

    queue = ProcessingQueue(GpuGate(), publish)
    queue.enqueue(_job("a", [_step()], on_finished=lambda: done.append("a")))
    queue.enqueue(_job("b", [_step()], on_finished=lambda: done.append("b")))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert done == ["a", "b"]


def test_crash_in_a_job_publishes_failed_and_the_queue_continues():
    queue, rec = _make()
    done: list[str] = []
    queue.enqueue(_job("a", [_step()], on_finished=lambda: done.append("a")))
    queue.enqueue(_job("b", [_step()], on_finished=lambda: done.append("b")))
    original = queue._process

    def flaky(job):
        if job.session_id == "a":
            raise RuntimeError("bug")
        original(job)

    queue._process = flaky
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert rec.of("a")[-1].state == "failed"
    assert done == ["b"]


def test_non_gpu_step_raising_step_cancelled_counts_as_failed():
    queue, rec = _make()
    ran: list[str] = []

    def cancelled(token, progress):
        raise StepCancelled

    queue.enqueue(_job("a", [_step(run=cancelled), _step(run=lambda t, p: ran.append("next"))]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert ran == ["next"]
    assert rec.of("a")[-1].state == "done"


def test_gpu_step_raising_step_cancelled_without_a_cancelled_token_is_not_retried():
    queue, _ = _make()
    runs = {"n": 0}

    def spurious(token, progress):
        runs["n"] += 1
        raise StepCancelled

    queue.enqueue(_job("a", [_step(gpu=True, run=spurious)]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert runs["n"] == 1


def test_enqueue_reports_whether_the_meeting_was_accepted():
    queue, _ = _make()
    assert queue.enqueue(_job("a", [_step()])) is True
    assert queue.enqueue(_job("a", [_step()])) is False


def test_a_step_aborting_the_job_ends_it_failed_without_later_steps_or_on_finished():
    queue, rec = _make()
    ran: list[str] = []

    def abort(token, progress):
        raise AbortJob("repair failed")

    queue.enqueue(
        _job(
            "a",
            [_step(run=abort), _step(run=lambda t, p: ran.append("later"))],
            on_finished=lambda: ran.append("finished"),
        )
    )
    queue.enqueue(_job("b", [_step(run=lambda t, p: ran.append("b"))]))
    queue.start()
    assert queue.wait_idle(TIMEOUT)
    queue.stop()
    assert ran == ["b"]  # the queue goes on with the next meeting
    assert rec.of("a")[-1].state == "failed"
    assert queue.contains("a") is False


def test_stop_cancels_the_running_step_and_runs_nothing_more():
    queue, recorder = _make()
    started = threading.Event()
    log: list[str] = []
    finished: list[str] = []

    def cancellable(token, progress):  # e.g. a CPU diarizer child, terminated on cancel
        started.set()
        cancelled = threading.Event()
        token.on_cancel(cancelled.set)
        assert cancelled.wait(TIMEOUT)
        log.append("cancelled")
        raise StepCancelled

    steps = [_step(StepKind.DIARIZE, run=cancellable), _step(run=lambda t, p: log.append("index"))]
    queue.enqueue(_job("a", steps, on_finished=lambda: finished.append("a")))
    queue.enqueue(_job("b", [_step(run=lambda t, p: log.append("b"))]))
    queue.start()
    assert started.wait(TIMEOUT)

    queue.stop()

    assert log == ["cancelled"]  # no later step, no later job
    assert finished == []  # the meeting stays finalizing: resumed at the next start
    assert not [s for s in recorder.of("a") if s.state in ("done", "failed")]


def test_a_step_that_ignores_the_cancel_still_stops_the_job_at_the_next_step():
    queue, _ = _make()
    started = threading.Event()
    log: list[str] = []

    def stubborn(token, progress):
        started.set()
        while not token.cancelled:
            threading.Event().wait(0.01)
        log.append("returned")  # e.g. a failure reported as an error, not a cancel

    queue.enqueue(_job("a", [_step(run=stubborn), _step(run=lambda t, p: log.append("next"))]))
    queue.start()
    assert started.wait(TIMEOUT)

    queue.stop()

    assert log == ["returned"]


def test_stop_before_any_job_is_harmless():
    queue, _ = _make()
    queue.stop()  # never started
    queue.start()
    queue.stop()
