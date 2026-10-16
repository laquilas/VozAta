from __future__ import annotations

import threading
import time

import pytest

from tests.api.conftest import START_ERROR, RecordingBroadcaster, SessionFactory
from tests.fakes import FakeLocalizer
from vozata.api.session_manager import (
    NoActiveSessionError,
    SessionConflictError,
    SessionManager,
    StartOptions,
)
from vozata.domain import Channel, ConversationLanguage, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.session import SessionStartError
from vozata.storage.session_store import SessionStore

OPTIONS = StartOptions(language=ConversationLanguage.PT, mic_device=9)


def test_start_returns_the_summary_and_passes_the_options(
    manager: SessionManager, factory: SessionFactory
) -> None:
    summary = manager.start(OPTIONS)

    assert summary == {
        "id": "20261015_202358",
        "status": "recording",
        "started_at": "2026-10-15T20:23:58-03:00",
        "ended_at": None,
        "duration_seconds": 0.0,
        "language": "pt",
        "has_minutes": False,
    }
    assert factory.sessions[0].options == OPTIONS
    manager.stop()
    assert manager.wait_until_finished(5)


def test_a_second_start_conflicts_until_finalization_ends(
    manager: SessionManager, factory: SessionFactory
) -> None:
    factory.stop_gate = threading.Event()
    manager.start(OPTIONS)

    with pytest.raises(SessionConflictError):
        manager.start(OPTIONS)
    stopped = manager.stop()
    with pytest.raises(SessionConflictError):  # still finalizing
        manager.start(OPTIONS)

    factory.stop_gate.set()
    assert manager.wait_until_finished(5)
    assert stopped["status"] == "finalizing"
    assert manager.current is None
    manager.start(OPTIONS)  # free again
    factory.stop_gate = None
    factory.sessions[-1].stop_gate = None
    manager.stop()
    assert manager.wait_until_finished(5)


def test_pause_resume_and_stop_drive_the_session(
    manager: SessionManager, factory: SessionFactory, store: SessionStore
) -> None:
    manager.start(OPTIONS)

    assert manager.pause()["status"] == "paused"
    assert manager.resume()["status"] == "recording"
    assert manager.stop()["status"] == "finalizing"
    assert manager.wait_until_finished(5)

    assert factory.sessions[0].calls == ["start", "pause", "resume", "stop"]
    assert store.read_meta("20261015_202358")["status"] == "done"


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_commands_without_an_active_session_raise(manager: SessionManager, action: str) -> None:
    with pytest.raises(NoActiveSessionError):
        getattr(manager, action)()


def test_a_failed_start_leaves_no_active_session(
    manager: SessionManager, factory: SessionFactory
) -> None:
    factory.start_error = START_ERROR

    with pytest.raises(SessionStartError):
        manager.start(OPTIONS)

    assert manager.current is None
    assert manager.status_message()["data"] == {"status": "idle"}


def test_observer_events_become_contract_envelopes(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    manager.start(OPTIONS)
    observer = factory.sessions[0].observer
    segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Oi.", ())

    observer.on_segment(segment)
    observer.on_language_detected(ConversationLanguage.ES)
    observer.on_minutes_ready("20261015_202358")
    observer.on_error("minutes_failed", "offline")
    manager.stop()
    assert manager.wait_until_finished(5)

    session_id = "20261015_202358"
    [(sid, data)] = broadcaster.of("segment")
    assert sid == session_id
    assert data["label"] == "labels.mic" and data["text"] == "Oi." and data["edited"] is False
    assert broadcaster.of("language_detected") == [(session_id, {"language": "es"})]
    assert broadcaster.of("minutes_ready") == [(session_id, {"session_id": session_id})]
    assert broadcaster.of("error") == [
        (session_id, {"code": "minutes_failed", "message": "offline"})
    ]
    statuses = [data["status"] for _, data in broadcaster.of("status")]
    assert statuses[0] == "recording"
    assert statuses[-2:] == ["finalizing", "done"]


def test_level_events_are_throttled_per_channel(
    factory: SessionFactory, store: SessionStore, broadcaster: RecordingBroadcaster
) -> None:
    now = [0.0]
    manager = SessionManager(
        factory, store, broadcaster, SpeakerLabeler(FakeLocalizer()), clock=lambda: now[0]
    )
    manager.start(OPTIONS)
    observer = factory.sessions[0].observer

    for t in (0.0, 0.05, 0.1, 0.12, 0.25):
        now[0] = t
        observer.on_level(Channel.MIC, -20.0)
    observer.on_level(Channel.SYSTEM, -30.0)

    levels = broadcaster.of("level")
    assert [data["channel"] for _, data in levels] == ["mic", "mic", "mic", "system"]
    manager.stop()
    assert manager.wait_until_finished(5)


def test_status_heartbeat_while_recording(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    manager.start(OPTIONS)
    factory.sessions[0].duration_seconds = 4.0

    deadline = time.monotonic() + 2
    while len(broadcaster.of("status")) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    manager.stop()
    assert manager.wait_until_finished(5)

    beats = [data for _, data in broadcaster.of("status") if data["duration_seconds"] == 4.0]
    assert beats and beats[0]["status"] == "recording"


def test_status_message_describes_the_current_session(
    manager: SessionManager, factory: SessionFactory
) -> None:
    assert manager.status_message() == {
        "type": "status",
        "session_id": None,
        "data": {"status": "idle"},
    }

    manager.start(OPTIONS)
    factory.sessions[0].duration_seconds = 7.5

    assert manager.status_message() == {
        "type": "status",
        "session_id": "20261015_202358",
        "data": {"status": "recording", "duration_seconds": 7.5},
    }
    manager.stop()
    assert manager.wait_until_finished(5)


def test_a_failing_finalization_still_frees_the_manager(
    manager: SessionManager, factory: SessionFactory
) -> None:
    manager.start(OPTIONS)

    def broken_stop() -> None:
        raise RuntimeError("disk full")

    factory.sessions[0].stop = broken_stop  # type: ignore[method-assign]
    manager.stop()

    assert manager.wait_until_finished(5)
    assert manager.current is None


def test_events_before_the_session_folder_exists_have_no_session_id(
    factory: SessionFactory, store: SessionStore, broadcaster: RecordingBroadcaster
) -> None:
    def early_factory(observer, options):  # type: ignore[no-untyped-def]
        observer.on_level(Channel.MIC, -40.0)  # before start(): id not known yet
        return factory(observer, options)

    manager = SessionManager(early_factory, store, broadcaster, SpeakerLabeler(FakeLocalizer()))
    manager.start(OPTIONS)

    assert broadcaster.of("level")[0][0] is None
    manager.stop()
    assert manager.wait_until_finished(5)


def test_heartbeat_stops_once_finalization_starts(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    factory.stop_gate = threading.Event()
    manager.start(OPTIONS)
    manager.stop()
    time.sleep(0.1)  # several heartbeat intervals while finalizing
    beats_while_finalizing = [
        data for _, data in broadcaster.of("status") if data["status"] == "finalizing"
    ]

    factory.stop_gate.set()
    assert manager.wait_until_finished(5)
    assert len(beats_while_finalizing) == 1  # only the session's own status change


def test_events_while_the_session_id_is_not_readable_have_no_session_id(
    factory: SessionFactory, store: SessionStore, broadcaster: RecordingBroadcaster
) -> None:
    def factory_with_early_event(observer, options):  # type: ignore[no-untyped-def]
        session = factory(observer, options)
        original_start = session.start

        def start() -> None:
            observer.on_error("loading", "model loading")  # session exists, folder not yet
            original_start()

        session.start = start  # type: ignore[method-assign]
        return session

    manager = SessionManager(
        factory_with_early_event, store, broadcaster, SpeakerLabeler(FakeLocalizer())
    )
    manager.start(OPTIONS)

    assert broadcaster.of("error")[0][0] is None
    manager.stop()
    assert manager.wait_until_finished(5)
