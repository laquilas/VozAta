"""`POST /ask`: answer in the background, streaming `answer_chunk` and then `answer_done`."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from vozata.api.ws import EventBroadcaster
from vozata.ports import LanguageModelError, Localizer
from vozata.qa.answerer import Answer

_log = logging.getLogger(__name__)


class Answerer(Protocol):
    """What `AskJob` needs from `MeetingAnswerer`."""

    def answer(
        self, question: str, session_id: str | None, on_chunk: Callable[[str], None]
    ) -> Answer: ...


AnswererFactory = Callable[[], Answerer]


class AskJob:
    """One question at a time: `start` returns False while another answer is streaming.

    Events carry the scope as `session_id` (None for all sessions). `answer_done` always closes an
    answer; on failure it has no citations and a localized `error`.
    """

    def __init__(
        self, build_answerer: AnswererFactory, broadcaster: EventBroadcaster, localizer: Localizer
    ) -> None:
        self._build = build_answerer
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._lock = threading.Lock()
        self._busy = False
        self._thread: threading.Thread | None = None

    def start(self, answer_id: str, question: str, session_id: str | None) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self._thread = threading.Thread(
            target=self._run, args=(answer_id, question, session_id), name="ask", daemon=True
        )
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the last answer finished (tests, shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def _run(self, answer_id: str, question: str, session_id: str | None) -> None:
        publish = self._broadcaster.publish
        citations: list[dict[str, object]] = []
        error: str | None = None
        try:
            answer = self._build().answer(
                question,
                session_id,
                lambda text: publish(
                    "answer_chunk", session_id, {"answer_id": answer_id, "text": text}
                ),
            )
            citations = [citation.to_dict() for citation in answer.citations]
        except LanguageModelError as failure:
            _log.warning("Answering %s failed: %s", answer_id, failure)
            error = self._t("errors.api.answer_failed", reason=failure)
        except Exception:
            _log.exception("Answering %s failed", answer_id)
            error = self._t("errors.api.internal_error")
        finally:
            with self._lock:
                self._busy = False
        publish(
            "answer_done",
            session_id,
            {"answer_id": answer_id, "citations": citations, "error": error},
        )
