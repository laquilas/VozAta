"""Data types of the background processing queue: a job is an ordered tuple of steps."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from vozata.processing.cancel import CancelToken

log = logging.getLogger(__name__)


class StepKind(StrEnum):
    REPAIR = "repair"
    TRANSCRIBE = "transcribe"
    FINALIZE = "finalize"
    MIX = "mix"
    DIARIZE = "diarize"
    MINUTES = "minutes"
    ACTION_ITEMS = "action_items"
    INDEX = "index"


# `finalize` and `mix` are silent: events report the shown step that follows them.
HIDDEN_KINDS = frozenset({StepKind.FINALIZE, StepKind.MIX})


@dataclass(frozen=True)
class Step:
    kind: StepKind
    weight: float
    gpu: bool
    run: Callable[[CancelToken, Callable[[float], None]], None]


def _nothing() -> None:
    return None


@dataclass(frozen=True)
class ProcessingJob:
    session_id: str
    steps: tuple[Step, ...]
    on_finished: Callable[[], None]
    before: Callable[[], None] = field(default=_nothing)


def shown_kind(steps: tuple[Step, ...], index: int) -> StepKind | None:
    """The kind events report while `steps[index]` runs (hidden kinds map to the next shown)."""
    for step in steps[index:]:
        if step.kind not in HIDDEN_KINDS:
            return step.kind
    for step in reversed(steps[:index]):
        if step.kind not in HIDDEN_KINDS:
            return step.kind
    return None


def run_job_inline(job: ProcessingJob) -> None:
    """Run `job` on this thread, never cancelled (CLI `record`): like the queue, a failing
    `before` or step is logged and the next step still runs."""
    try:
        job.before()
    except Exception:
        log.exception("preparing the processing of meeting %s failed", job.session_id)
    token = CancelToken()
    for step in job.steps:
        try:
            step.run(token, lambda fraction: None)
        except Exception:
            log.exception("step %s of meeting %s failed", step.kind.value, job.session_id)
    job.on_finished()
