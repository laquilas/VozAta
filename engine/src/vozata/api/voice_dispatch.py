"""Run a voice command heard while recording (phase 50)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Protocol

from vozata.api.partial_minutes_job import PartialMinutesJob, PartialRequest
from vozata.api.request_log import RequestLog
from vozata.api.ws import EventBroadcaster
from vozata.domain import VoiceCommand
from vozata.ports import Localizer

_log = logging.getLogger(__name__)


class QuestionRunner(Protocol):
    """What the dispatcher needs from the voice `AskJob`."""

    def start(self, answer_id: str, question: str, session_id: str | None) -> bool: ...


class VoiceDispatch(Protocol):
    """What a session's voice command listener calls (phase 59: with the second, and repeats)."""

    def __call__(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None: ...

    def repeated(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None: ...


class VoiceCommandDispatcher:
    """`voice_command {action, phrase, question, answer_id, request_id, at}`, then the action:
    `minutes` writes minutes so far (origin `voice`) up to `at`, the second the wake word was said
    (phase 59), `ask` streams the answer of `question` as `answer_chunk` / `answer_done` with
    `answer_id`. A job already running answers `error` `voice_command_busy`.

    With a `requests` log every command is an entry of the meeting's history: `recognized`, then
    `running` (or `failed` when busy); the job finishes it. A command repeated within the cooldown
    is an `ignored` entry (`voice_command_repeated`)."""

    def __init__(
        self,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        partial_minutes: PartialMinutesJob | None,
        questions: QuestionRunner | None,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
        requests: RequestLog | None = None,
    ) -> None:
        self._requests = requests
        self._broadcaster = broadcaster
        self._localizer = localizer
        self._partial_minutes = partial_minutes
        self._questions = questions
        self._new_id = new_id

    def __call__(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None:
        answer_id = f"voice-{self._new_id()}" if command.action == "ask" else None
        request_id = self._begin(session_id, command, at, "recognized", answer_id=answer_id)
        self._broadcaster.publish(
            "voice_command",
            session_id,
            {**command.to_dict(), "answer_id": answer_id, "request_id": request_id, "at": at},
        )
        if command.action == "minutes" and self._partial_minutes is not None:
            self._update(session_id, request_id, "running")  # before the job can finish it
            end = at if at is not None and at > 0 else None  # leave the command itself out
            request = PartialRequest(session_id, 0.0, end, "voice", True, None, request_id)
            started = self._partial_minutes.start(request) is not None
        elif answer_id is not None and command.question and self._questions is not None:
            self._update(session_id, request_id, "running")
            started = self._questions.start(answer_id, command.question, session_id)
        else:
            _log.warning("Voice command %r has nothing to run", command.phrase)
            self._update(session_id, request_id, "failed", "voice_command_unavailable")
            return
        if not started:
            self._update(session_id, request_id, "failed", "voice_command_busy")
            message = self._localizer.t("errors.api.voice_command_busy")
            self._broadcaster.publish(
                "error", session_id, {"code": "voice_command_busy", "message": message}
            )

    def repeated(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None:
        """Said again within the cooldown: nothing runs, the history says so (phase 59)."""
        self._begin(session_id, command, at, "ignored", message="voice_command_repeated")

    def _begin(
        self,
        session_id: str,
        command: VoiceCommand,
        at: float | None,
        status: str,
        *,
        answer_id: str | None = None,
        message: str | None = None,
    ) -> str | None:
        if self._requests is None:
            return None
        kind = "ask" if command.action == "ask" else "minutes_so_far"
        text = (command.question or command.phrase) if command.action == "ask" else command.phrase
        return self._requests.begin(
            session_id,
            kind,
            "voice",
            text=text,
            at=at,
            status=status,
            result_id=answer_id,
            message=message,
        )

    def _update(
        self, session_id: str, request_id: str | None, status: str, code: str | None = None
    ) -> None:
        if self._requests is not None and request_id is not None:
            self._requests.update(session_id, request_id, status, message=code)
