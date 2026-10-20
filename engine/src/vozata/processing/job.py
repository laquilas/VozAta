"""Data types of the background processing queue: a job is an ordered tuple of steps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from vozata.processing.cancel import CancelToken


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
