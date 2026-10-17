"""`POST /sessions/{id}/action-items`: extract in the background, report through events."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_action_items import Extractor, write_session_action_items
from vozata.minutes.session_minutes import EmptyTranscriptError
from vozata.ports import LanguageModelError, Localizer
from vozata.storage.session_store import SessionStore

_log = logging.getLogger(__name__)


class ActionItemsJob:
    """Callable `(session_id)`: starts a background extraction and returns at once.

    Success publishes `action_items_ready {session_id, count}`; failures publish a localized
    `error` event (`empty_transcript`, `action_items_failed`).
    """

    def __init__(
        self,
        store: SessionStore,
        build_extractor: Callable[[], Extractor],
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
    ) -> None:
        self._store = store
        self._build = build_extractor
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._thread: threading.Thread | None = None

    def __call__(self, session_id: str) -> None:
        self._thread = threading.Thread(target=self._run, args=(session_id,), name="action-items")
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the last job finished (tests, shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def _run(self, session_id: str) -> None:
        publish = self._broadcaster.publish
        try:
            items = write_session_action_items(
                self._store, session_id, self._build(), self._labeler
            )
        except EmptyTranscriptError:
            message = self._t("errors.api.empty_transcript", id=session_id)
            publish("error", session_id, {"code": "empty_transcript", "message": message})
        except LanguageModelError as error:
            _log.warning("Extracting action items for %s failed: %s", session_id, error)
            message = self._t("errors.api.action_items_failed", reason=error)
            publish("error", session_id, {"code": "action_items_failed", "message": message})
        except Exception:
            _log.exception("Extracting action items for %s failed", session_id)
            message = self._t("errors.api.internal_error")
            publish("error", session_id, {"code": "action_items_failed", "message": message})
        else:
            data = {"session_id": session_id, "count": len(items)}
            publish("action_items_ready", session_id, data)
