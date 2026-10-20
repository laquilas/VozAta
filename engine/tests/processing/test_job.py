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
