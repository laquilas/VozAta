"""A finished meeting's language-model job in the processing queue (phase 40).

`POST /sessions/{id}/minutes` and `POST /sessions/{id}/action-items` no longer run on their own
thread: each enqueues a job of one model step (minutes or action items) and the `index` step. The
model step goes through the GPU gate when the language model runs on the local GPU (read when
each attempt starts), so a live recording or Ask pre-empts it; it is then redone with a freshly
built model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer, SessionRepository
from vozata.processing.cancel import CancelToken
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.processing.queue import ProcessingQueue
from vozata.processing.session_job import INDEX_WEIGHT

_log = logging.getLogger(__name__)


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


class QueuedModelJob:
    """Base of `MinutesJob` and `ActionItemsJob`: what they share to queue their work.

    `uses_gpu()` (the language model runs on the local GPU) is read when each attempt starts;
    `index(session_id)` re-indexes the meeting after a successful model step only.
    """

    def __init__(
        self,
        store: SessionRepository,
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        *,
        queue: ProcessingQueue,
        uses_gpu: Callable[[], bool] = lambda: False,
        index: Callable[[str], None] = lambda session_id: None,
    ) -> None:
        self._store = store
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._queue = queue
        self._uses_gpu = uses_gpu
        self._index = index

    def _enqueue(
        self,
        session_id: str,
        kind: StepKind,
        weight: float,
        attempt: Callable[[CancelToken], bool],
    ) -> bool:
        """Queue `kind` (one `attempt(token)` per try; True when it wrote its result), then
        `index`; False when the meeting is already in the queue. Nothing runs when it finishes:
        the meeting keeps its status."""
        written = [False]

        def model(token: CancelToken, progress: Callable[[float], None]) -> None:
            written[0] = attempt(token)

        def reindex(token: CancelToken, progress: Callable[[float], None]) -> None:
            if not written[0]:
                return
            try:
                self._index(session_id)
            except Exception as error:
                _log.exception("Indexing %s for search failed", session_id)
                message = self._t("errors.session.index_failed", reason=str(error))
                self._error(session_id, "index_failed", message)

        steps = (
            Step(kind, weight, False, model, gpu_now=self._uses_gpu),
            Step(StepKind.INDEX, INDEX_WEIGHT, False, reindex),
        )
        return self._queue.enqueue(
            ProcessingJob(session_id=session_id, steps=steps, on_finished=lambda: None)
        )

    def _error(self, session_id: str, code: str, message: str) -> None:
        self._broadcaster.publish("error", session_id, {"code": code, "message": message})
