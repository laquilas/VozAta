"""`POST /sessions/{id}/action-items`: extract in the processing queue, report through events."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from vozata.api.model_job import Cancels, Progress, model_job
from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_action_items import Extractor, write_session_action_items
from vozata.minutes.session_minutes import EmptyTranscriptError
from vozata.ports import LanguageModelError, Localizer, SessionRepository
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.job import StepKind
from vozata.processing.queue import ProcessingQueue
from vozata.processing.session_job import ACTION_ITEMS_WEIGHT

_log = logging.getLogger(__name__)


class ActionItemsJob:
    """Callable `(session_id)`: queues an extraction (phase 40) and returns whether it was queued
    (False: the meeting is already in the queue).

    Success publishes `action_items_ready {session_id, count}`; failures publish a localized
    `error` event (`empty_transcript`, `action_items_failed`). Each attempt builds its own
    extractor; `uses_gpu()` puts the step behind the GPU gate; `index(session_id)` follows.
    """

    def __init__(
        self,
        store: SessionRepository,
        build_extractor: Callable[[], Extractor],
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        *,
        queue: ProcessingQueue,
        uses_gpu: Callable[[], bool] = lambda: False,
        index: Callable[[str], None] = lambda session_id: None,
    ) -> None:
        self._store = store
        self._build = build_extractor
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._queue = queue
        self._uses_gpu = uses_gpu
        self._index = index

    def __call__(self, session_id: str) -> bool:
        run = functools.partial(self._run, session_id)
        job = model_job(
            session_id,
            StepKind.ACTION_ITEMS,
            ACTION_ITEMS_WEIGHT,
            self._uses_gpu(),
            run,
            self._index,
        )
        return self._queue.enqueue(job)

    def _run(self, session_id: str, token: CancelToken, progress: Progress) -> None:
        publish = self._broadcaster.publish
        cancels = Cancels(token)
        try:
            token.raise_if_cancelled()
            extractor = cancels.watch(self._build())
            items = write_session_action_items(self._store, session_id, extractor, self._labeler)
        except StepCancelled:
            raise
        except EmptyTranscriptError:
            message = self._t("errors.api.empty_transcript", id=session_id)
            publish("error", session_id, {"code": "empty_transcript", "message": message})
        except Exception as error:
            if token.cancelled:  # pre-empted: the queue redoes the step
                raise StepCancelled from error
            if isinstance(error, LanguageModelError):
                _log.warning("Extracting action items for %s failed: %s", session_id, error)
                message = self._t("errors.api.action_items_failed", reason=error)
            else:
                _log.exception("Extracting action items for %s failed", session_id)
                message = self._t("errors.api.internal_error")
            publish("error", session_id, {"code": "action_items_failed", "message": message})
        else:
            data = {"session_id": session_id, "count": len(items)}
            publish("action_items_ready", session_id, data)
        finally:
            cancels.close()
