"""`POST /sessions/{id}/minutes`: regenerate in the processing queue, report through events."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from vozata.api.model_job import Cancels, Progress, model_job
from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_minutes import (
    EmptyTranscriptError,
    GeneratorFactory,
    write_session_minutes,
)
from vozata.ports import LanguageModelError, Localizer, SessionRepository
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.job import StepKind
from vozata.processing.queue import ProcessingQueue
from vozata.processing.session_job import MINUTES_WEIGHT

_log = logging.getLogger(__name__)


class MinutesJob:
    """Callable `(session_id, template)`: queues a regeneration (phase 40) and returns whether it
    was queued (False: the meeting is already in the queue).

    Success publishes `minutes_ready`; failures publish a localized `error` event. Each attempt
    builds its own generator; `uses_gpu()` (the language model runs on the local GPU) puts the
    step behind the GPU gate. `index(session_id)` re-indexes the meeting afterwards.
    """

    def __init__(
        self,
        store: SessionRepository,
        build_generator: GeneratorFactory,
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        *,
        queue: ProcessingQueue,
        uses_gpu: Callable[[], bool] = lambda: False,
        index: Callable[[str], None] = lambda session_id: None,
    ) -> None:
        self._store = store
        self._build_generator = build_generator
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._queue = queue
        self._uses_gpu = uses_gpu
        self._index = index

    def __call__(self, session_id: str, template: str | None = None) -> bool:
        """`template` None: the one stored in `session.json`, else `MINUTES_TEMPLATE`."""
        run = functools.partial(self._run, session_id, template)
        job = model_job(
            session_id, StepKind.MINUTES, MINUTES_WEIGHT, self._uses_gpu(), run, self._index
        )
        return self._queue.enqueue(job)

    def _run(
        self, session_id: str, template: str | None, token: CancelToken, progress: Progress
    ) -> None:
        publish = self._broadcaster.publish
        cancels = Cancels(token)

        def build(template_id: str | None) -> MinutesGenerator:
            token.raise_if_cancelled()
            return cancels.watch(self._build_generator(template_id))

        try:
            write_session_minutes(self._store, session_id, build, self._labeler, template)
        except StepCancelled:
            raise
        except EmptyTranscriptError:
            message = self._t("errors.api.empty_transcript", id=session_id)
            publish("error", session_id, {"code": "empty_transcript", "message": message})
        except Exception as error:
            if token.cancelled:  # pre-empted: the queue redoes the step
                raise StepCancelled from error
            if not isinstance(error, LanguageModelError):
                raise
            _log.warning("Regenerating minutes for %s failed: %s", session_id, error)
            message = self._t("errors.api.minutes_failed", reason=error)
            publish("error", session_id, {"code": "minutes_failed", "message": message})
        else:
            publish("minutes_ready", session_id, {"session_id": session_id})
        finally:
            cancels.close()
