"""`POST /sessions/{id}/partial-minutes`: minutes of part of a meeting, in the background (48)."""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from vozata.api.ws import EventBroadcaster
from vozata.labels import SpeakerLabeler
from vozata.minutes.partial_minutes import write_partial_minutes
from vozata.minutes.session_minutes import EmptyTranscriptError, GeneratorFactory
from vozata.ports import LanguageModelError, LlmUnreachableError, Localizer, SessionRepository
from vozata.processing.gpu_gate import GpuGate, GpuUser

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PartialRequest:
    session_id: str
    start: float
    end: float | None
    origin: str  # "button" | "voice" | "range"
    live: bool  # the meeting is being recorded: "what was said so far"
    template: str | None = None


class PartialMinutesJob:
    """One partial minutes at a time, outside the processing queue: a meeting being recorded must
    get them now, like an Ask answer (phase 48). `start` returns the new id, or None while
    another one is being written.

    With a `gate` and `uses_gpu()` true it holds the Ask GPU priority (the queue's running GPU
    step is redone later). Success publishes `partial_minutes_ready`; failures a localized
    `error` (`empty_range`, `llm_unreachable`, `partial_minutes_failed`).
    """

    def __init__(
        self,
        build_generator: GeneratorFactory,
        store: SessionRepository,
        labeler: SpeakerLabeler,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        *,
        gate: GpuGate | None = None,
        uses_gpu: Callable[[], bool] = lambda: False,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    ) -> None:
        self._build = build_generator
        self._store = store
        self._labeler = labeler
        self._broadcaster = broadcaster
        self._localizer = localizer
        self._gate = gate
        self._uses_gpu = uses_gpu
        self._new_id = new_id
        self._lock = threading.Lock()
        self._busy = False
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(self, request: PartialRequest) -> str | None:
        with self._lock:
            if self._busy:
                return None
            self._busy = True
        partial_id = self._new_id()
        self._thread = threading.Thread(
            target=self._run, args=(request, partial_id), name="partial-minutes", daemon=True
        )
        self._thread.start()
        return partial_id

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the last one finished (tests, shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def _priority(self) -> AbstractContextManager[None]:
        if self._gate is not None and self._uses_gpu():
            return self._gate.priority(GpuUser.ASK)
        return contextlib.nullcontext()

    def _run(self, request: PartialRequest, partial_id: str) -> None:
        session_id = request.session_id
        t = self._localizer.t
        try:
            with self._priority():
                item = write_partial_minutes(
                    self._store,
                    session_id,
                    self._build,
                    self._labeler,
                    self._localizer,
                    start=request.start,
                    end=request.end,
                    origin=request.origin,
                    live=request.live,
                    template=request.template,
                    new_id=lambda: partial_id,
                )
        except EmptyTranscriptError:
            self._error(session_id, "empty_range", t("errors.api.empty_range"))
        except LlmUnreachableError as error:
            _log.warning("Partial minutes of %s failed: %s", session_id, error)
            message = t("errors.llm_unreachable.minutes", host=error.host)
            self._error(session_id, "llm_unreachable", message)
        except LanguageModelError as error:
            _log.warning("Partial minutes of %s failed: %s", session_id, error)
            message = t("errors.api.partial_minutes_failed", reason=error)
            self._error(session_id, "partial_minutes_failed", message)
        except Exception:
            _log.exception("Partial minutes of %s failed", session_id)
            self._error(session_id, "partial_minutes_failed", t("errors.api.internal_error"))
        else:
            self._broadcaster.publish(
                "partial_minutes_ready",
                session_id,
                {
                    "partial_id": item.id,
                    "start": item.start,
                    "end": item.end,
                    "origin": item.origin,
                },
            )
        finally:
            with self._lock:
                self._busy = False

    def _error(self, session_id: str, code: str, message: str) -> None:
        self._broadcaster.publish("error", session_id, {"code": code, "message": message})
