"""`POST /sessions/{id}/minutes`: regenerate in the background, report through events."""

from __future__ import annotations

import logging
import threading

from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_minutes import (
    EmptyTranscriptError,
    GeneratorFactory,
    write_session_minutes,
)
from vozata.ports import LanguageModelError, Localizer
from vozata.storage.session_store import SessionStore

_log = logging.getLogger(__name__)


class MinutesJob:
    """Callable `(session_id, template)`: starts a background regeneration and returns at once.

    Success publishes `minutes_ready`; failures publish a localized `error` event.
    """

    def __init__(
        self,
        store: SessionStore,
        build_generator: GeneratorFactory,
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
    ) -> None:
        self._store = store
        self._build_generator = build_generator
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._thread: threading.Thread | None = None

    def __call__(self, session_id: str, template: str | None = None) -> None:
        """`template` None: the one stored in `session.json`, else `MINUTES_TEMPLATE`."""
        self._thread = threading.Thread(
            target=self._run, args=(session_id, template), name="minutes"
        )
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the last job finished (tests, shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def _run(self, session_id: str, template: str | None) -> None:
        publish = self._broadcaster.publish
        try:
            write_session_minutes(
                self._store, session_id, self._build_generator, self._labeler, template
            )
        except EmptyTranscriptError:
            message = self._t("errors.api.empty_transcript", id=session_id)
            publish("error", session_id, {"code": "empty_transcript", "message": message})
        except LanguageModelError as error:
            _log.warning("Regenerating minutes for %s failed: %s", session_id, error)
            message = self._t("errors.api.minutes_failed", reason=error)
            publish("error", session_id, {"code": "minutes_failed", "message": message})
        else:
            publish("minutes_ready", session_id, {"session_id": session_id})
