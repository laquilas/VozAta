"""Fakes shared by the API tests: a session that writes real metadata, a recording broadcaster."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeLocalizer
from vozata.api.session_manager import SessionManager, StartOptions
from vozata.api.ws import EventBroadcaster
from vozata.domain import ConversationLanguage, SessionStatus
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionObserver
from vozata.session import SessionStartError
from vozata.storage.session_store import SessionStore

BRT = timezone(timedelta(hours=-3))


class RecordingBroadcaster(EventBroadcaster):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[tuple[str, str | None, dict[str, Any]]] = []

    def publish(self, kind: str, session_id: str | None, data: dict[str, Any]) -> None:
        self.published.append((kind, session_id, data))
        super().publish(kind, session_id, data)

    def of(self, kind: str) -> list[tuple[str | None, dict[str, Any]]]:
        return [(session_id, data) for name, session_id, data in self.published if name == kind]


class FakeSession:
    """Mimics `RecordingSession`: real `session.json` through the store, observer events."""

    def __init__(
        self,
        store: SessionStore,
        observer: SessionObserver,
        options: StartOptions,
        *,
        stop_gate: threading.Event | None = None,
        start_error: Exception | None = None,
        moment: datetime = datetime(2026, 10, 15, 20, 23, 58, tzinfo=BRT),
    ) -> None:
        self.store = store
        self.observer = observer
        self.options = options
        self.stop_gate = stop_gate
        self.start_error = start_error
        self.moment = moment
        self.status: SessionStatus | None = None
        self.duration_seconds = 0.0
        self._id: str | None = None
        self.calls: list[str] = []

    @property
    def id(self) -> str:
        if self._id is None:
            raise RuntimeError("The session has not started")
        return self._id

    def start(self) -> None:
        self.calls.append("start")
        if self.start_error is not None:
            raise self.start_error
        self._id = self.store.create(self.moment).id
        language = (self.options.language or ConversationLanguage.EN).value
        self.meta = {
            "id": self._id,
            "status": "recording",
            "started_at": self.moment.isoformat(),
            "ended_at": None,
            "language": language,
        }
        self._set(SessionStatus.RECORDING)

    def pause(self) -> None:
        self.calls.append("pause")
        self._set(SessionStatus.PAUSED)

    def resume(self) -> None:
        self.calls.append("resume")
        self._set(SessionStatus.RECORDING)

    def stop(self) -> None:
        self.calls.append("stop")
        self._set(SessionStatus.FINALIZING)
        if self.stop_gate is not None:
            assert self.stop_gate.wait(5)
        self.meta["ended_at"] = (self.moment + timedelta(seconds=90)).isoformat()
        self._set(SessionStatus.DONE)

    def _set(self, status: SessionStatus) -> None:
        self.status = status
        self.meta["status"] = status.value
        self.store.write_meta(self.id, self.meta)
        self.observer.on_status(status, self.duration_seconds)


class SessionFactory:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self.sessions: list[FakeSession] = []
        self.stop_gate: threading.Event | None = None
        self.start_error: Exception | None = None

    def __call__(self, observer: SessionObserver, options: StartOptions) -> FakeSession:
        session = FakeSession(
            self.store,
            observer,
            options,
            stop_gate=self.stop_gate,
            start_error=self.start_error,
        )
        self.sessions.append(session)
        return session


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "recordings")


@pytest.fixture
def factory(store: SessionStore) -> SessionFactory:
    return SessionFactory(store)


@pytest.fixture
def broadcaster() -> RecordingBroadcaster:
    return RecordingBroadcaster()


@pytest.fixture
def manager(
    factory: SessionFactory, store: SessionStore, broadcaster: RecordingBroadcaster
) -> SessionManager:
    labeler = SpeakerLabeler(FakeLocalizer())
    return SessionManager(factory, store, broadcaster, labeler, status_interval=0.02)


START_ERROR = SessionStartError("device_timeout", "The mic did not open")
