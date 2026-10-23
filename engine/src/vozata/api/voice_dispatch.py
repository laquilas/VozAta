"""Run a voice command heard while recording (phase 50)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Protocol

from vozata.api.partial_minutes_job import PartialMinutesJob, PartialRequest
from vozata.api.ws import EventBroadcaster
from vozata.domain import VoiceCommand
from vozata.ports import Localizer

_log = logging.getLogger(__name__)


class QuestionRunner(Protocol):
    """What the dispatcher needs from the voice `AskJob`."""

    def start(self, answer_id: str, question: str, session_id: str | None) -> bool: ...


class VoiceCommandDispatcher:
    """`voice_command {action, phrase, question, answer_id}`, then the action: `minutes` writes
    minutes so far (origin `voice`), `ask` streams the answer of `question` as `answer_chunk` /
    `answer_done` with `answer_id`. A job already running answers `error` `voice_command_busy`."""

    def __init__(
        self,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        partial_minutes: PartialMinutesJob | None,
        questions: QuestionRunner | None,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    ) -> None:
        self._broadcaster = broadcaster
        self._localizer = localizer
        self._partial_minutes = partial_minutes
        self._questions = questions
        self._new_id = new_id

    def __call__(self, session_id: str, command: VoiceCommand) -> None:
        answer_id = f"voice-{self._new_id()}" if command.action == "ask" else None
        self._broadcaster.publish(
            "voice_command", session_id, {**command.to_dict(), "answer_id": answer_id}
        )
        if command.action == "minutes" and self._partial_minutes is not None:
            request = PartialRequest(session_id, 0.0, None, "voice", True)
            started = self._partial_minutes.start(request) is not None
        elif answer_id is not None and command.question and self._questions is not None:
            started = self._questions.start(answer_id, command.question, session_id)
        else:
            _log.warning("Voice command %r has nothing to run", command.phrase)
            return
        if not started:
            message = self._localizer.t("errors.api.voice_command_busy")
            self._broadcaster.publish(
                "error", session_id, {"code": "voice_command_busy", "message": message}
            )
