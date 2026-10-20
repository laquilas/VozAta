"""A finished meeting's language-model job in the processing queue (phase 40).

`POST /sessions/{id}/minutes` and `POST /sessions/{id}/action-items` no longer run on their own
thread: each enqueues a job of one model step (minutes or action items) and the `index` step. The
model step goes through the GPU gate when the language model runs on the local GPU, so a live
recording, Ask or a Config test pre-empts it; it is then redone with a freshly built model.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from vozata.processing.cancel import CancelToken
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.processing.session_job import INDEX_WEIGHT

Progress = Callable[[float], None]


class Cancellable(Protocol):
    def cancel(self) -> None: ...


class Cancels:
    """Ties every model built during one step attempt to its token (`close()` undoes it)."""

    def __init__(self, token: CancelToken) -> None:
        self._token = token
        self._undo: list[Callable[[], None]] = []

    def watch[T: Cancellable](self, model: T) -> T:
        self._undo.append(self._token.on_cancel(model.cancel))
        return model

    def close(self) -> None:
        for undo in self._undo:
            undo()
        self._undo.clear()


def model_job(
    session_id: str,
    kind: StepKind,
    weight: float,
    gpu: bool,
    run: Callable[[CancelToken, Progress], None],
    index: Callable[[str], None],
) -> ProcessingJob:
    """`kind` (on the GPU gate when `gpu`), then `index` the meeting; nothing when it finishes:
    the meeting keeps its status."""
    steps = (
        Step(kind, weight, gpu, run),
        Step(StepKind.INDEX, INDEX_WEIGHT, False, lambda token, progress: index(session_id)),
    )
    return ProcessingJob(session_id=session_id, steps=steps, on_finished=lambda: None)
