"""The API's single recording session: lifecycle, events and background finalization."""

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
from vozata.ports import Localizer, SessionObserver
from vozata.storage.session_store import SessionStore

LEVEL_INTERVAL = 0.1  # ~10 Hz per channel
STATUS_INTERVAL = 1.0  # `status` heartbeat while recording or paused

_log = logging.getLogger(__name__)


class SessionConflictError(RuntimeError):
    """A session is already recording, paused or finalizing (`409 session_already_active`)."""


class NoActiveSessionError(RuntimeError):
    """No session is recording or paused (`409 no_active_session`)."""


class SessionNotInterruptedError(RuntimeError):
    """`POST /sessions/{id}/recover` on a session that is not `interrupted` (phase 17)."""


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

    def stop(self) -> None: ...


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


SessionFactory = Callable[[SessionObserver, StartOptions], Session]


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


class SessionManager:
    """Owns at most one active session (recording, paused or finalizing).

    `stop()` returns at once: finalization (transcript drain, WAVs, minutes) runs on a background
    thread and reports through `status` events.
    """

    def __init__(
        self,
        factory: SessionFactory,
        store: SessionStore,
        broadcaster: EventBroadcaster,
        labeler: SpeakerLabeler,
        clock: Callable[[], float] = time.monotonic,
        status_interval: float = STATUS_INTERVAL,
        recovery: Recovery | None = None,
        localizer: Localizer | None = None,
    ) -> None:
        self._factory = factory
        self._store = store
        self._broadcaster = broadcaster
        self._labeler = labeler
        self._clock = clock
        self._status_interval = status_interval
        self._recovery = recovery
        self._localizer = localizer
        self._lock = threading.Lock()
        self._session: Session | None = None
        self._recovering: str | None = None  # id of the session being recovered (phase 17)
        self._finished = threading.Event()

    @property
    def current(self) -> Session | None:
        return self._session

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
        """Begin finalization on a background thread; the summary reports `finalizing`."""
        session = self._active()
        summary = self.summary(session)
        # Not a daemon: the process waits for the WAVs, transcript and minutes to be written.
        threading.Thread(target=self._finalize, args=(session,), name="finalize").start()
        return {**summary, "status": SessionStatus.FINALIZING.value}

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
            try:
                return self._recovery.find_interrupted({i for i in live if i is not None})
            except Exception:
                _log.exception("Looking for interrupted sessions failed")
                return []

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        """Block until the last stopped or recovered session finished (tests, shutdown)."""
        return self._finished.wait(timeout)

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
        if session is None or session.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
            raise NoActiveSessionError
        return session

    def _finalize(self, session: Session) -> None:
        try:
            session.stop()
        except Exception:
            _log.exception("Finalizing session %s failed", session.id)
        finally:
            with self._lock:
                self._session = None
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
