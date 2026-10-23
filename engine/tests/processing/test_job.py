import pytest

from vozata.processing.job import ProcessingJob, Step, StepKind, shown_kind


def _step(kind: StepKind) -> Step:
    return Step(kind=kind, weight=1.0, gpu=False, run=lambda token, progress: None)


def test_hidden_kinds_report_the_next_shown_step():
    steps = (
        _step(StepKind.TRANSCRIBE),
        _step(StepKind.FINALIZE),
        _step(StepKind.MIX),
        _step(StepKind.DIARIZE),
    )
    assert [shown_kind(steps, i) for i in range(4)] == [
        StepKind.TRANSCRIBE,
        StepKind.DIARIZE,
        StepKind.DIARIZE,
        StepKind.DIARIZE,
    ]


def test_trailing_hidden_kind_falls_back_to_the_previous_shown_step():
    steps = (_step(StepKind.MINUTES), _step(StepKind.MIX))
    assert shown_kind(steps, 1) == StepKind.MINUTES


def test_only_hidden_kinds_report_nothing():
    assert shown_kind((_step(StepKind.FINALIZE),), 0) is None


def test_job_before_defaults_to_a_no_op():
    job = ProcessingJob("s1", (), on_finished=lambda: None)
    assert job.before() is None


def test_run_job_inline_runs_before_every_step_then_on_finished(caplog):
    from vozata.processing.job import run_job_inline

    log: list[str] = []

    def broken(token, progress):
        raise RuntimeError("step broke")

    def run(name):
        def step(token, progress):
            assert not token.cancelled
            progress(1.0)
            log.append(name)

        return step

    job = ProcessingJob(
        session_id="s1",
        steps=(
            Step(StepKind.TRANSCRIBE, 1.0, True, run("transcribe")),
            Step(StepKind.MINUTES, 1.0, True, broken),
            Step(StepKind.INDEX, 1.0, False, run("index")),
        ),
        on_finished=lambda: log.append("finished"),
        before=lambda: log.append("before"),
    )

    run_job_inline(job)

    assert log == ["before", "transcribe", "index", "finished"]
    assert "step broke" in caplog.text


def test_run_job_inline_continues_after_a_failing_before(caplog):
    from vozata.processing.job import run_job_inline

    log: list[str] = []

    def before():
        raise RuntimeError("wait broke")

    job = ProcessingJob(
        session_id="s1",
        steps=(Step(StepKind.INDEX, 1.0, False, lambda t, p: log.append("index")),),
        on_finished=lambda: log.append("finished"),
        before=before,
    )

    run_job_inline(job)

    assert log == ["index", "finished"]
    assert "wait broke" in caplog.text


def test_the_job_waits_for_the_live_pipeline_and_warns_while_it_does(caplog):
    import threading

    from vozata.processing.gpu_gate import GpuUsage
    from vozata.processing.session_job import JobParts, session_job

    closed = threading.Event()
    parts = JobParts(
        finisher=lambda models: None,  # type: ignore[arg-type, return-value]
        transcription=lambda: None,  # type: ignore[arg-type, return-value]
        diarize=False,
        minutes=False,
        action_items=False,
    )
    job = session_job(
        "s1",
        parts,
        GpuUsage(False, False, False),
        weight=2.0,
        closed=closed,
        on_finished=lambda: None,
        warn_every=0.01,
    )
    waiting = threading.Thread(target=job.before)

    waiting.start()
    threading.Event().wait(0.1)
    assert waiting.is_alive()  # no timeout: it keeps waiting
    closed.set()
    waiting.join(5)

    assert not waiting.is_alive()
    assert "still waiting for the live pipeline of meeting s1" in caplog.text


@pytest.mark.parametrize(
    ("usage", "gated"),
    [
        ((True, False), True),
        ((False, True), True),  # speech on the worker: a fallback must not race a recording
        ((False, False), False),
    ],
)
def test_the_transcribe_step_is_gated_when_speech_may_use_this_gpu(usage, gated):
    from vozata.processing.gpu_gate import GpuUsage
    from vozata.processing.session_job import JobParts, session_job

    speech, fallback = usage
    parts = JobParts(
        finisher=lambda models: None,  # type: ignore[arg-type, return-value]
        transcription=lambda: None,  # type: ignore[arg-type, return-value]
        diarize=False,
        minutes=False,
        action_items=False,
    )
    job = session_job(
        "s1",
        parts,
        GpuUsage(speech, False, False, speech_fallback=fallback),
        weight=2.0,
        closed=None,
        on_finished=lambda: None,
    )

    transcribe = next(step for step in job.steps if step.kind is StepKind.TRANSCRIBE)
    assert transcribe.gpu is gated


def test_run_job_inline_stops_at_an_aborting_step_without_on_finished():
    from vozata.processing.job import AbortJob, run_job_inline

    ran: list[str] = []

    def abort(token, progress):
        raise AbortJob("repair failed")

    job = ProcessingJob(
        "a",
        (
            Step(StepKind.REPAIR, 1.0, False, abort),
            Step(StepKind.INDEX, 1.0, False, lambda t, p: ran.append("index")),
        ),
        on_finished=lambda: ran.append("finished"),
    )

    run_job_inline(job)

    assert ran == []


def test_a_step_reads_its_gpu_use_at_each_attempt():
    gpu = [False]
    step = Step(StepKind.MINUTES, 1.0, True, lambda token, progress: None, gpu_now=lambda: gpu[0])

    first = step.uses_gpu()
    gpu[0] = True

    assert (first, step.uses_gpu()) == (False, True)
    assert Step(StepKind.MIX, 1.0, True, lambda token, progress: None).uses_gpu() is True


@pytest.mark.parametrize(
    ("speakers", "fallback", "gated"),
    [(True, False, True), (False, True, True), (False, False, False)],
)
def test_the_diarize_step_is_gated_when_speakers_may_use_this_gpu(speakers, fallback, gated):
    import contextlib

    from vozata.processing.gpu_gate import GpuUsage
    from vozata.processing.session_job import JobParts, session_job

    parts = JobParts(
        finisher=lambda kind: contextlib.nullcontext(None),  # type: ignore[arg-type, return-value]
        transcription=lambda: None,  # type: ignore[arg-type, return-value]
        diarize=True,
        minutes=False,
        action_items=False,
    )
    job = session_job(
        "s1",
        parts,
        GpuUsage(False, speakers, False, speakers_fallback=fallback),
        weight=2.0,
        closed=None,
        on_finished=lambda: None,
    )

    diarize = next(step for step in job.steps if step.kind is StepKind.DIARIZE)
    assert diarize.uses_gpu() is gated
