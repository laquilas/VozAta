"""Fakes shared by the API tests: a session that writes real metadata, a recording broadcaster."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeLocalizer, FakeRecycler
from vozata.api.session_manager import SessionManager, StartOptions
from vozata.api.ws import EventBroadcaster
from vozata.domain import ConversationLanguage, SessionStatus
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionObserver
from vozata.session import SessionStartError
from vozata.storage.files.repository import FileSessionRepository
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
        store: FileSessionRepository,
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
        self._id = self.store.create(self.moment)
        language = (self.options.language or ConversationLanguage.EN).value
        self.meta = {
            "id": self._id,
            "status": "recording",
            "started_at": self.moment.isoformat(),
            "ended_at": None,
            "language": language,
        }
        if self.options.title is not None:
            self.meta["title"] = self.options.title
        self._set(SessionStatus.RECORDING)

    def pause(self) -> None:
        self.calls.append("pause")
        self._set(SessionStatus.PAUSED)

    def resume(self) -> None:
        self.calls.append("resume")
        self._set(SessionStatus.RECORDING)

    def set_title(self, title: str | None) -> None:
        self.calls.append("set_title")
        self.meta["title"] = title
        self.store.write_meta(self.id, self.meta)

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
    def __init__(self, store: FileSessionRepository) -> None:
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
def store(tmp_path: Path) -> FileSessionRepository:
    return FileSessionRepository(SessionStore(tmp_path / "recordings"))


@pytest.fixture
def factory(store: FileSessionRepository) -> SessionFactory:
    return SessionFactory(store)


@pytest.fixture
def broadcaster() -> RecordingBroadcaster:
    return RecordingBroadcaster()


@pytest.fixture
def manager(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> SessionManager:
    labeler = SpeakerLabeler(FakeLocalizer())
    return SessionManager(factory, store, broadcaster, labeler, status_interval=0.02)


START_ERROR = SessionStartError("device_timeout", "The mic did not open")


class FakeDevices:
    def __init__(self) -> None:
        from vozata.audio.devices import DeviceInfo

        self.mic = DeviceInfo(9, "Headset Mic", 2, 48000, False)
        self.loopback = DeviceInfo(10, "Speakers [Loopback]", 2, 48000, True)
        self.has_defaults = True

    def inputs(self):  # type: ignore[no-untyped-def]
        return [self.mic]

    def loopbacks(self):  # type: ignore[no-untyped-def]
        return [self.loopback]

    def default_input(self):  # type: ignore[no-untyped-def]
        return self.mic if self.has_defaults else None

    def default_loopback(self):  # type: ignore[no-untyped-def]
        return self.loopback if self.has_defaults else None


class Api:
    """The real app over fakes, plus handles on the fakes for assertions."""

    def __init__(
        self, tmp_path: Path, settings: Any = None, recovery: Any = None, migration: Any = None
    ) -> None:
        from fastapi.testclient import TestClient

        from vozata.api.app import create_app
        from vozata.api.container import ApiContainer
        from vozata.api.system_info import GpuInfo
        from vozata.config import Settings

        self.settings = settings or Settings(output_dir=tmp_path / "recordings")
        self.recycler = FakeRecycler(tmp_path / "recycle-bin")  # never the real one (phase 36)
        self.store = FileSessionRepository(SessionStore(self.settings.output_dir), self.recycler)
        self.factory = SessionFactory(self.store)
        self.broadcaster = RecordingBroadcaster()
        self.labeler = SpeakerLabeler(FakeLocalizer())
        from vozata.i18n import TomlLocalizer as _Localizer

        self.manager = SessionManager(
            self.factory,
            self.store,
            self.broadcaster,
            self.labeler,
            status_interval=60,
            recovery=recovery(self.store) if recovery is not None else None,  # phase 17
            localizer=_Localizer(self.settings.app_language),
        )
        self.devices = FakeDevices()
        self.gpu = GpuInfo(True, "RTX 3050", 6144)
        self.reachable = True
        self.regenerated: list[tuple[str, str | None]] = []
        from vozata.bootstrap import EXPORTERS
        from vozata.i18n import TomlLocalizer
        from vozata.settings_file import SettingsFile

        self.env_file = tmp_path / ".env"
        self.vocabulary_file = tmp_path / "vocabulary.txt"
        self.settings_file = SettingsFile(self.env_file, self.settings, environ={})

        container = ApiContainer(
            settings=self.settings,
            settings_file=self.settings_file,
            exporters={name: build() for name, build in EXPORTERS.items()},
            localizer=TomlLocalizer(self.settings.app_language),
            labeler=self.labeler,
            store=self.store,
            broadcaster=self.broadcaster,
            manager=self.manager,
            devices=self.devices,
            gpu_info=lambda: self.gpu,
            llm_reachable=lambda: self.reachable,
            regenerate_minutes=lambda session_id, template: self.regenerated.append(
                (session_id, template)
            ),
            vocabulary_file=lambda: self.vocabulary_file,
            migration=migration(self) if migration is not None else None,  # phase 33
        )
        self.app = create_app(container)
        self.client = TestClient(self.app, raise_server_exceptions=False)


@pytest.fixture
def api(tmp_path: Path):  # type: ignore[no-untyped-def]
    api = Api(tmp_path)
    with api.client:
        yield api
    current = api.manager.current
    if current is not None:
        for session in api.factory.sessions:
            if session.stop_gate is not None:
                session.stop_gate.set()  # release a finalization a test held back
        if current.status in (SessionStatus.RECORDING, SessionStatus.PAUSED):
            api.manager.stop()
        assert api.manager.wait_until_finished(5)
