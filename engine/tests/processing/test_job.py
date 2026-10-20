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
