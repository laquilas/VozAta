"""The API's single recording session: lifecycle, events, and the hand-over of a stopped
meeting to the processing queue (phase 40)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol

from vozata.api.payloads import segment_payload, session_summary
from vozata.api.ws import EventBroadcaster
from vozata.domain import (
    Channel,
    ConversationLanguage,
    SessionStatus,
    TranscriptSegment,
    TranslationTarget,
)
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer, SessionObserver, SessionRepository
from vozata.processing.job import ProcessingJob
from vozata.processing.queue import ProcessingQueue

LEVEL_INTERVAL = 0.1  # ~10 Hz per channel
STATUS_INTERVAL = 1.0  # `status` heartbeat while recording or paused

_log = logging.getLogger(__name__)


class SessionConflictError(RuntimeError):
    """A session is already recording, paused or still stopping its capture, or one is being
    recovered (`409 session_already_active`)."""


class NoActiveSessionError(RuntimeError):
    """No session is recording or paused (`409 no_active_session`)."""


class SessionNotInterruptedError(RuntimeError):
    """`POST /sessions/{id}/recover` on a session that is not `interrupted` (phase 17)."""


class SessionBeingRecoveredError(RuntimeError):
    """The session is being recovered right now (`409 session_being_recovered`, phase 35)."""


class SessionStillActiveError(RuntimeError):
    """Delete of the session being recorded, finalized or recovered (`409`, phase 36)."""


class Recovery(Protocol):
    """Crash recovery (`storage.recovery.SessionRecovery`, phase 17)."""

    def find_interrupted(self, live_ids: Collection[str] = ()) -> list[str]: ...

    def is_interrupted(self, session_id: str) -> bool: ...

    def recover(self, session_id: str, observer: SessionObserver) -> bool: ...


class Session(Protocol):
    status: SessionStatus | None

    @property
    def id(self) -> str: ...

    @property
    def duration_seconds(self) -> float: ...

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop_capture(self) -> threading.Event: ...

    def set_title(self, title: str | None) -> None: ...


@dataclass(frozen=True)
class StartOptions:
    language: ConversationLanguage | None = None
    mic_device: int | None = None
    system_device: int | None = None
    template: str | None = None  # minutes template id (phase 20); None = MINUTES_TEMPLATE
    vocabulary: tuple[str, ...] = ()  # this meeting's terms (phase 19), merged with the glossary
    translate_to: TranslationTarget | None = (
        None  # live translation (phase 29); None = TRANSLATE_TO
    )
    title: str | None = None  # meeting title (phase 35), already normalized; None = untitled


SessionFactory = Callable[[SessionObserver, StartOptions], Session]
# (session id, repair first, the abandoned live pipeline's `closed` event) -> the meeting's job
JobFactory = Callable[[str, bool, threading.Event | None], ProcessingJob]


class _EventObserver:
    """`SessionObserver` → WebSocket envelopes; `level` throttled per channel."""

    def __init__(
        self,
        broadcaster: EventBroadcaster,
        labeler: SpeakerLabeler,
        session_id: Callable[[], str | None],
        clock: Callable[[], float],
    ) -> None:
        self._publish = broadcaster.publish
        self._labeler = labeler
        self._session_id = session_id
        self._clock = clock
        self._level_at: dict[Channel, float] = {}

    def on_status(self, status: SessionStatus, duration_seconds: float) -> None:
        self._send("status", {"status": status.value, "duration_seconds": duration_seconds})

    def on_level(self, channel: Channel, rms_db: float) -> None:
        now = self._clock()
        if now - self._level_at.get(channel, float("-inf")) < LEVEL_INTERVAL:
            return
        self._level_at[channel] = now
        self._send("level", {"channel": channel.value, "rms_db": rms_db})

    def on_segment(self, segment: TranscriptSegment) -> None:
        self._send("segment", segment_payload(segment, self._labeler))

    def on_language_detected(self, language: ConversationLanguage) -> None:
        self._send("language_detected", {"language": language.value})

    def on_minutes_ready(self, session_id: str) -> None:
        self._send("minutes_ready", {"session_id": session_id})

    def on_action_items_ready(self, session_id: str, count: int) -> None:
        self._send("action_items_ready", {"session_id": session_id, "count": count})

    def on_speakers_relabeled(self, session_id: str) -> None:
        self._send("speakers_relabeled", {"session_id": session_id})

    def on_partial(self, channel: Channel, speaker_id: str, start: float, text: str) -> None:
        label = self._labeler.label(speaker_id)
        self._send(
            "partial",
            {
                "channel": channel.value,
                "speaker_id": speaker_id,
                "label": label,
                "start": start,
                "text": text,
            },
        )

    def on_model_loading(self, loading: bool) -> None:
        self._send("model_loading", {"loading": loading})

    def on_translation(self, segment_id: str, language: str, text: str) -> None:
        self._send("translation", {"segment_id": segment_id, "language": language, "text": text})

    def on_error(self, code: str, message: str) -> None:
        self._send("error", {"code": code, "message": message})

    def _send(self, kind: str, data: dict[str, Any]) -> None:
        self._publish(kind, self._session_id(), data)


def session_observer(
    broadcaster: EventBroadcaster,
    labeler: SpeakerLabeler,
    session_id: str,
    clock: Callable[[], float] = time.monotonic,
) -> SessionObserver:
    """The events of a meeting that is no longer recording (its processing job, phase 40)."""
    return _EventObserver(broadcaster, labeler, lambda: session_id, clock)


class SessionManager:
    """Owns at most one recording (or paused) session.

    `stop()` returns at once: `stop_capture()` runs on a short-lived thread, then the slot is
    released and the meeting's job (`job_factory`) is put on the processing `queue`, which finishes
    it in the background and reports through `processing` and `status` events (phase 40).
    """

    def __init__(
        self,
        factory: SessionFactory,
        store: SessionRepository,
        broadcaster: EventBroadcaster,
        labeler: SpeakerLabeler,
        clock: Callable[[], float] = time.monotonic,
        status_interval: float = STATUS_INTERVAL,
        recovery: Recovery | None = None,
        localizer: Localizer | None = None,
        *,
        queue: ProcessingQueue,
        job_factory: JobFactory,
    ) -> None:
        self._factory = factory
        self._store = store
        self._broadcaster = broadcaster
        self._labeler = labeler
        self._clock = clock
        self._status_interval = status_interval
        self._recovery = recovery
        self._localizer = localizer
        self._queue = queue
        self._job_factory = job_factory
        self._lock = threading.Lock()
        self._session: Session | None = None
        self._stopping: Session | None = None  # stop accepted, `stop_capture()` running
        self._recovering: str | None = None  # id of the session being recovered (phase 17)
        self._finished = threading.Event()

    @property
    def current(self) -> Session | None:
        return self._session

    @property
    def busy(self) -> bool:
        """A session records or is paused, one is being recovered, or meetings wait in the
        processing queue (phase 33: the folder import waits meanwhile)."""
        return (
            self._session is not None or self._recovering is not None or bool(self._queue.pending())
        )

    def start(self, options: StartOptions) -> dict[str, Any]:
        with self._lock:
            if self._session is not None or self._recovering is not None:
                raise SessionConflictError
            holder: list[Session] = []
            observer = _EventObserver(
                self._broadcaster, self._labeler, lambda: _started_id(holder), self._clock
            )
            session = self._factory(observer, options)
            holder.append(session)
            session.start()
            self._session = session
            self._finished.clear()
        threading.Thread(target=self._heartbeat, args=(session,), daemon=True).start()
        return self.summary(session)

    def pause(self) -> dict[str, Any]:
        session = self._active()
        session.pause()
        return self.summary(session)

    def resume(self) -> dict[str, Any]:
        session = self._active()
        session.resume()
        return self.summary(session)

    def stop(self) -> dict[str, Any]:
        """Stop capture on a short-lived thread, then free the slot and queue the meeting; the
        summary reports `finalizing`. A second stop meanwhile raises `NoActiveSessionError`."""
        with self._lock:
            session = self._active()
            self._stopping = session
        summary = self.summary(session)
        threading.Thread(target=self._stop_capture, args=(session,), name="stop-capture").start()
        return {**summary, "status": SessionStatus.FINALIZING.value}

    def rename(self, session_id: str, title: str | None) -> dict[str, Any]:
        """Set the meeting title (normalized; None clears it) and return the summary (phase 35).

        The session being recorded or finalized renames itself, because it rewrites its metadata
        until it is done; any other session is rewritten through the repository. A session being
        recovered raises `SessionBeingRecoveredError`; an unknown one `SessionNotFoundError`.
        """
        with self._lock:
            session = self._session
            if session is not None and _started_id([session]) == session_id:
                session.set_title(title)
                return self.summary(session)
            if self._recovering == session_id:
                raise SessionBeingRecoveredError(session_id)
            meta = self._store.read_meta(session_id)
            self._store.write_meta(session_id, {**meta, "title": title})
        return session_summary(self._store, session_id)

    def delete(self, session_id: str) -> None:
        """Delete a finished session through the repository (phase 36). The session being
        recorded, finalized or recovered raises `SessionStillActiveError`; held under the lock,
        so it cannot start being recovered meanwhile."""
        with self._lock:
            self._check_not_live(session_id)
            self._store.delete(session_id)

    def check_finished(self, session_id: str) -> None:
        """`SessionStillActiveError` for the session being recorded, finalized or recovered."""
        with self._lock:
            self._check_not_live(session_id)

    def _check_not_live(self, session_id: str) -> None:
        session = self._session
        live = session is not None and _started_id([session]) == session_id
        if live or self._recovering == session_id:
            raise SessionStillActiveError(session_id)

    def discard_audio(self, session_id: str, discard: Callable[[str], None]) -> None:
        """Remove a finished session's audio with `discard` (phase 39), under the same rule and
        lock as `delete`: the session being recorded, finalized or recovered raises
        `SessionStillActiveError`."""
        with self._lock:
            self._check_not_live(session_id)
            discard(session_id)

    def recover(self, session_id: str) -> None:
        """Finish an `interrupted` session on a background thread (phase 17).

        It takes the place of the active session until done (VRAM rule: never next to a
        recording), so `start()` meanwhile raises `SessionConflictError`. Progress arrives as
        `status` events with the session's id; a failed repair as an `error` event.
        """
        recovery = self._recovery
        with self._lock:
            if self._session is not None or self._recovering is not None:
                raise SessionConflictError
            if recovery is None or not recovery.is_interrupted(session_id):
                raise SessionNotInterruptedError(session_id)
            self._recovering = session_id
            self._finished.clear()
        observer = _EventObserver(self._broadcaster, self._labeler, lambda: session_id, self._clock)
        threading.Thread(
            target=self._recover, args=(recovery, session_id, observer), name="recover"
        ).start()

    def interrupted_sessions(self) -> list[str]:
        """Sessions a crash cut short (marked `interrupted` now if needed); `[]` on failure."""
        if self._recovery is None:
            return []
        with self._lock:  # a session being started is not interrupted
            live = {self._recovering, _started_id([self._session] if self._session else [])}
            live |= {state.session_id for state in self._queue.pending()}  # finalizing, queued
            try:
                return self._recovery.find_interrupted({i for i in live if i is not None})
            except Exception:
                _log.exception("Looking for interrupted sessions failed")
                return []

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        """Block until the last stopped meeting was queued (or the recovery ended) and the
        processing queue is idle (tests)."""
        return self._finished.wait(timeout) and self._queue.wait_idle(timeout)

    def summary(self, session: Session) -> dict[str, Any]:
        live = session.duration_seconds if session is self._session else None
        return session_summary(self._store, session.id, live)

    def status_message(self) -> dict[str, Any]:
        """The `status` envelope sent to a client when it connects."""
        session = self._session
        if session is None or session.status is None:
            return {"type": "status", "session_id": None, "data": {"status": "idle"}}
        data = {"status": session.status.value, "duration_seconds": session.duration_seconds}
        return {"type": "status", "session_id": session.id, "data": data}

    def _active(self) -> Session:
        session = self._session
        recording = session is not None and session.status in (
            SessionStatus.RECORDING,
            SessionStatus.PAUSED,
        )
        if session is None or not recording or session is self._stopping:
            raise NoActiveSessionError
        return session

    def _stop_capture(self, session: Session) -> None:
        closed: threading.Event | None = None
        try:
            closed = session.stop_capture()
        except Exception:
            _log.exception("Stopping the capture of session %s failed", session.id)
        try:
            with self._lock:
                self._session = None
                self._stopping = None
                self._queue.enqueue(self._job_factory(session.id, False, closed))
        except Exception:
            _log.exception("Queueing session %s for processing failed", session.id)
        finally:
            self._finished.set()

    def _recover(self, recovery: Recovery, session_id: str, observer: SessionObserver) -> None:
        try:
            recovery.recover(session_id, observer)
        except Exception as error:
            _log.exception("Recovering session %s failed", session_id)
            message = (
                self._localizer.t("errors.api.recovery_failed", id=session_id, reason=error)
                if self._localizer is not None
                else str(error)
            )
            observer.on_error("recovery_failed", message)
        finally:
            with self._lock:
                self._recovering = None
            self._finished.set()

    def _heartbeat(self, session: Session) -> None:
        while not self._finished.wait(self._status_interval):
            if session.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
                return
            data = {"status": session.status.value, "duration_seconds": session.duration_seconds}
            self._broadcaster.publish("status", session.id, data)


def _started_id(holder: list[Session]) -> str | None:
    try:
        return holder[0].id if holder else None
    except RuntimeError:  # events before the session folder exists
        return None
