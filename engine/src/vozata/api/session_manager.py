"""The API's single recording session: lifecycle, events, and the hand-over of a stopped
meeting to the processing queue (phase 40)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
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
from vozata.ports import SessionObserver, SessionRepository
from vozata.processing.job import ProcessingJob
from vozata.processing.queue import ProcessingQueue

LEVEL_INTERVAL = 0.1  # ~10 Hz per channel
STATUS_INTERVAL = 1.0  # `status` heartbeat while recording or paused
STOP_WAIT = 10.0  # how long `start()` waits for a stop in progress to free the slot
_PENDING = frozenset({"queued", "running", "paused"})  # processing states clients are sent

_log = logging.getLogger(__name__)


class SessionConflictError(RuntimeError):
    """A session is already recording, paused or still stopping its capture
    (`409 session_already_active`)."""


class NoActiveSessionError(RuntimeError):
    """No session is recording or paused (`409 no_active_session`)."""


class SessionNotInterruptedError(RuntimeError):
    """`POST /sessions/{id}/recover` on a session that is not `interrupted` (phase 17)."""


class SessionStillActiveError(RuntimeError):
    """Delete of the session being recorded, finalized, queued or processed (`409`, phase 36)."""


class Recovery(Protocol):
    """Crash recovery (`storage.recovery.SessionRecovery`, phase 17); the repair and the stop
    steps themselves run as a processing job (phase 40)."""

    def find_interrupted(self, live_ids: Collection[str] = ()) -> list[str]: ...

    def is_interrupted(self, session_id: str) -> bool: ...


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
    live_transcription: bool | None = None  # phase 41; None = LIVE_TRANSCRIPTION


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
        *,
        queue: ProcessingQueue,
        job_factory: JobFactory,
        stop_wait: float = STOP_WAIT,
    ) -> None:
        self._factory = factory
        self._store = store
        self._broadcaster = broadcaster
        self._labeler = labeler
        self._clock = clock
        self._status_interval = status_interval
        self._recovery = recovery
        self._queue = queue
        self._job_factory = job_factory
        self._stop_wait = stop_wait
        self._lock = threading.Lock()
        self._session: Session | None = None
        self._stopping: Session | None = None  # stop accepted, `stop_capture()` running
        self._finished = threading.Event()
        self._finished.set()  # nothing is being stopped; `start()` clears it

    @property
    def current(self) -> Session | None:
        return self._session

    @property
    def busy(self) -> bool:
        """A session records or is paused, or meetings wait in the processing queue (phase 33:
        the folder import waits meanwhile)."""
        return self._session is not None or bool(self._queue.pending())

    def start(self, options: StartOptions) -> dict[str, Any]:
        """Start a recording. While a stop is still releasing its capture (sources, PortAudio),
        wait up to `stop_wait` seconds (outside the lock) for the slot, so a Start right after the
        stop was accepted succeeds; `SessionConflictError` when the slot is still taken."""
        with self._lock:
            stopping = self._stopping is not None
        if stopping:
            self._finished.wait(self._stop_wait)
        with self._lock:
            if self._session is not None:
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
        queued or processed may be renamed too; an unknown one raises `SessionNotFoundError`.
        """
        with self._lock:
            session = self._session
            if session is not None and _started_id([session]) == session_id:
                session.set_title(title)
                return self.summary(session)
            meta = self._store.read_meta(session_id)
            self._store.write_meta(session_id, {**meta, "title": title})
        return session_summary(self._store, session_id, processing=self.processing(session_id))

    def delete(self, session_id: str) -> None:
        """Delete a finished session through the repository (phase 36). The session being
        recorded, finalized, queued or processed raises `SessionStillActiveError`; held under the
        lock, so it cannot be queued meanwhile."""
        with self._lock:
            self._check_not_live(session_id)
            self._store.delete(session_id)

    def check_finished(self, session_id: str) -> None:
        """`SessionStillActiveError` for a session being recorded, finalized, queued or run."""
        with self._lock:
            self._check_not_live(session_id)

    def _check_not_live(self, session_id: str) -> None:
        session = self._session
        live = session is not None and _started_id([session]) == session_id
        if live or self._queue.contains(session_id):
            raise SessionStillActiveError(session_id)

    def discard_audio(self, session_id: str, discard: Callable[[str], None]) -> None:
        """Remove a finished session's audio with `discard` (phase 39), under the same rule and
        lock as `delete`: the session being recorded, finalized, queued or processed raises
        `SessionStillActiveError`."""
        with self._lock:
            self._check_not_live(session_id)
            discard(session_id)

    def recover(self, session_id: str) -> None:
        """Queue an `interrupted` session's job, which starts with the repair step (phase 17/40).

        It does not take the recording slot: the queue processes it in the background, reporting
        through `processing` and `status` events; a failed repair ends the job `failed` with an
        `error` event and the session stays `interrupted`. A session already queued is left as is.
        """
        recovery = self._recovery
        with self._lock:
            if recovery is None or not recovery.is_interrupted(session_id):
                raise SessionNotInterruptedError(session_id)
            if not self._queue.contains(session_id):
                self._queue.enqueue(self._job_factory(session_id, True, None))

    def resume_pending(self) -> list[str]:
        """Queue the meetings a restart (or a crash after Stop) left unfinished; return their ids.

        Every session `finalizing` with `capture_ended_at` that is not live is enqueued, oldest
        first, with the repair step first (phase 40). That also covers a meeting whose job could
        not be created at Stop. Call it at start, before `interrupted_sessions()`.
        """
        with self._lock:
            pending: list[tuple[float, str]] = []
            live = {_started_id([self._session] if self._session else [])}
            for session_id in self._store.list_sessions():
                try:
                    meta = self._store.read_meta(session_id)
                except (OSError, ValueError):
                    _log.warning("Skipping %s: unreadable session.json", session_id)
                    continue
                ended = meta.get("capture_ended_at")
                if (
                    meta.get("status") == SessionStatus.FINALIZING.value
                    and ended
                    and session_id not in live
                    and not self._queue.contains(session_id)
                ):
                    pending.append((_moment(str(ended)), session_id))
            queued: list[str] = []
            for _, session_id in sorted(pending):
                try:
                    if self._queue.enqueue(self._job_factory(session_id, True, None)):
                        queued.append(session_id)
                except Exception:
                    _log.exception("Resuming session %s failed", session_id)
            return queued

    def interrupted_sessions(self) -> list[str]:
        """Sessions a crash cut short (marked `interrupted` now if needed); `[]` on failure."""
        if self._recovery is None:
            return []
        with self._lock:  # a session being started is not interrupted
            live = {_started_id([self._session] if self._session else [])}
            live |= {state.session_id for state in self._queue.pending()}  # finalizing, queued
            try:
                return self._recovery.find_interrupted({i for i in live if i is not None})
            except Exception:
                _log.exception("Looking for interrupted sessions failed")
                return []

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        """Block until the last stopped meeting was queued and the processing queue is idle
        (tests)."""
        return self._finished.wait(timeout) and self._queue.wait_idle(timeout)

    def summary(self, session: Session) -> dict[str, Any]:
        live = session.duration_seconds if session is self._session else None
        return session_summary(self._store, session.id, live, self.processing(session.id))

    def processing(self, session_id: str) -> dict[str, Any] | None:
        """The `processing` field of a meeting (phase 40): its queue state, or None when it is
        not queued or processed (a job that just ended `done`/`failed` counts as gone)."""
        state = self._queue.state(session_id)
        return state.to_payload() if state is not None and state.state in _PENDING else None

    def processing_messages(self) -> list[dict[str, Any]]:
        """One `processing` envelope per meeting still queued or processed, running first (the
        snapshot a client gets when it connects, phase 40)."""
        return [
            {"type": "processing", "session_id": state.session_id, "data": state.to_payload()}
            for state in self._queue.pending()
            if state.state in _PENDING
        ]

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

    def _heartbeat(self, session: Session) -> None:
        while not self._finished.wait(self._status_interval):
            if session.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
                return
            data = {"status": session.status.value, "duration_seconds": session.duration_seconds}
            self._broadcaster.publish("status", session.id, data)


def _moment(stamp: str) -> float:
    """`capture_ended_at` as a timestamp (offsets and DST compared properly); 0 if unreadable."""
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return 0.0


def _started_id(holder: list[Session]) -> str | None:
    try:
        return holder[0].id if holder else None
    except RuntimeError:  # events before the session folder exists
        return None
