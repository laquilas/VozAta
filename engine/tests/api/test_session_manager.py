from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

import pytest

from tests.api.conftest import (
    START_ERROR,
    FakeJobs,
    RecordingBroadcaster,
    SessionFactory,
    make_manager,
)
from tests.test_session_recover import make_session_folder
from vozata.api.session_manager import (
    NoActiveSessionError,
    SessionConflictError,
    SessionManager,
    StartOptions,
)
from vozata.domain import Channel, ConversationLanguage, TranscriptSegment
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.session import SessionStartError
from vozata.storage.files.repository import FileSessionRepository

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
        "title": None,
        "speaker_count": 0,
        "has_action_items": False,
        "template": None,
        "processing": None,
    }
    assert factory.sessions[0].options == OPTIONS
    manager.stop()
    assert manager.wait_until_finished(5)


def test_manager_start_refused_until_stop_capture_released_the_slot(
    manager: SessionManager, factory: SessionFactory
) -> None:
    factory.stop_gate = threading.Event()  # holds the stop inside `stop_capture()`
    manager.start(OPTIONS)

    with pytest.raises(SessionConflictError):
        manager.start(OPTIONS)
    stopped = manager.stop()
    with pytest.raises(SessionConflictError):  # capture still stopping: never two captures
        manager.start(OPTIONS)
    with pytest.raises(NoActiveSessionError):  # the stop was already accepted
        manager.stop()

    factory.stop_gate.set()
    _wait_until(lambda: manager.current is None)
    assert stopped["status"] == "finalizing"
    factory.stop_gate = None
    manager.start(OPTIONS)  # free again
    manager.stop()
    assert manager.wait_until_finished(5)
    assert [s.calls[-2:] for s in factory.sessions] == [["stop_capture", "finish"]] * 2


def test_manager_start_allowed_after_stop_while_job_pending(
    manager: SessionManager, factory: SessionFactory, jobs: FakeJobs, store: FileSessionRepository
) -> None:
    jobs.hold = threading.Event()  # the first meeting's job runs until released
    manager.start(OPTIONS)
    manager.stop()
    _wait_until(lambda: manager.current is None)

    summary = manager.start(OPTIONS)  # the first meeting is still being processed
    jobs.hold.set()

    assert summary["status"] == "recording"
    assert summary["id"] == "20261015_202358_2"
    assert manager.busy
    manager.stop()
    assert manager.wait_until_finished(5)
    assert [store.read_meta(s.id)["status"] for s in factory.sessions] == ["done", "done"]
    assert [call[:2] for call in jobs.calls] == [(s.id, False) for s in factory.sessions]


def test_busy_while_recording_and_while_the_meeting_is_processed(
    manager: SessionManager, factory: SessionFactory, jobs: FakeJobs
) -> None:
    jobs.hold = threading.Event()
    assert not manager.busy

    manager.start(OPTIONS)
    assert manager.busy
    manager.stop()
    _wait_until(lambda: manager.current is None)
    assert manager.busy  # queued or being processed

    jobs.hold.set()
    assert manager.wait_until_finished(5)
    assert not manager.busy


def test_the_job_waits_for_the_abandoned_pipeline(
    manager: SessionManager, factory: SessionFactory, jobs: FakeJobs
) -> None:
    manager.start(OPTIONS)
    session = factory.sessions[0]
    session.closed = threading.Event()  # the live pipeline closes later
    manager.stop()
    _wait_until(lambda: manager.current is None)
    threading.Timer(0.2, session.closed.set).start()

    assert manager.wait_until_finished(5)
    assert jobs.seen_closed == [True]
    assert jobs.calls[0][2] is session.closed


def test_a_queued_meeting_is_not_reported_interrupted(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    seen: list[set[str]] = []

    class _Recovery:
        def find_interrupted(self, live_ids):  # type: ignore[no-untyped-def]
            seen.append(set(live_ids))
            return []

        def is_interrupted(self, session_id: str) -> bool:
            return False

        def recover(self, session_id, observer):  # type: ignore[no-untyped-def]
            return False

    jobs = FakeJobs(factory)
    jobs.hold = threading.Event()
    manager = make_manager(factory, store, broadcaster, jobs=jobs, recovery=_Recovery())
    manager.start(OPTIONS)
    manager.stop()
    _wait_until(lambda: manager.current is None)

    assert manager.interrupted_sessions() == []
    jobs.hold.set()
    assert manager.wait_until_finished(5)
    assert seen == [{"20261015_202358"}]


def _wait_until(condition) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "condition not met"
        time.sleep(0.005)


def test_pause_resume_and_stop_drive_the_session(
    manager: SessionManager, factory: SessionFactory, store: FileSessionRepository
) -> None:
    manager.start(OPTIONS)

    assert manager.pause()["status"] == "paused"
    assert manager.resume()["status"] == "recording"
    assert manager.stop()["status"] == "finalizing"
    assert manager.wait_until_finished(5)

    assert factory.sessions[0].calls == ["start", "pause", "resume", "stop_capture", "finish"]
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
    observer.on_action_items_ready("20261015_202358", 2)
    observer.on_speakers_relabeled("20261015_202358")
    observer.on_error("minutes_failed", "offline")
    manager.stop()
    assert manager.wait_until_finished(5)

    session_id = "20261015_202358"
    [(sid, data)] = broadcaster.of("segment")
    assert sid == session_id
    assert data["label"] == "labels.mic" and data["text"] == "Oi." and data["edited"] is False
    assert broadcaster.of("language_detected") == [(session_id, {"language": "es"})]
    assert broadcaster.of("minutes_ready") == [(session_id, {"session_id": session_id})]
    assert broadcaster.of("action_items_ready") == [
        (session_id, {"session_id": session_id, "count": 2})
    ]
    assert broadcaster.of("speakers_relabeled") == [(session_id, {"session_id": session_id})]
    assert broadcaster.of("error") == [
        (session_id, {"code": "minutes_failed", "message": "offline"})
    ]
    statuses = [data["status"] for _, data in broadcaster.of("status")]
    assert statuses[0] == "recording"
    assert statuses[-2:] == ["finalizing", "done"]


def test_level_events_are_throttled_per_channel(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    now = [0.0]
    manager = make_manager(factory, store, broadcaster, clock=lambda: now[0])
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

    def broken_stop() -> threading.Event:
        raise RuntimeError("disk full")

    factory.sessions[0].stop_capture = broken_stop  # type: ignore[method-assign]
    manager.stop()

    assert manager.wait_until_finished(5)
    assert manager.current is None
    manager.start(OPTIONS)  # the slot is free again
    manager.stop()
    assert manager.wait_until_finished(5)


def test_a_failing_job_factory_still_frees_the_manager(
    manager: SessionManager, factory: SessionFactory, jobs: FakeJobs
) -> None:
    manager.start(OPTIONS)
    factory.sessions.clear()  # the job cannot find its session

    manager.stop()

    assert manager.wait_until_finished(5)
    assert manager.current is None


def test_events_before_the_session_folder_exists_have_no_session_id(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    def early_factory(observer, options):  # type: ignore[no-untyped-def]
        observer.on_level(Channel.MIC, -40.0)  # before start(): id not known yet
        return factory(observer, options)

    manager = make_manager(early_factory, store, broadcaster)
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
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    def factory_with_early_event(observer, options):  # type: ignore[no-untyped-def]
        session = factory(observer, options)
        original_start = session.start

        def start() -> None:
            observer.on_error("loading", "model loading")  # session exists, folder not yet
            original_start()

        session.start = start  # type: ignore[method-assign]
        return session

    manager = make_manager(factory_with_early_event, store, broadcaster)
    manager.start(OPTIONS)

    assert broadcaster.of("error")[0][0] is None
    manager.stop()
    assert manager.wait_until_finished(5)


def test_partials_are_published_with_the_speaker_label(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    manager.start(OPTIONS)
    observer = factory.sessions[0].observer

    observer.on_partial(Channel.SYSTEM, "system", 12.5, "Vamos começ")
    observer.on_partial(Channel.SYSTEM, "system", 12.5, "")
    manager.stop()
    assert manager.wait_until_finished(5)

    session_id = "20261015_202358"
    base = {"channel": "system", "speaker_id": "system", "label": "labels.system", "start": 12.5}
    assert broadcaster.of("partial") == [
        (session_id, {**base, "text": "Vamos começ"}),
        (session_id, {**base, "text": ""}),
    ]


def test_model_loading_is_published_true_then_false(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    manager.start(OPTIONS)
    observer = factory.sessions[0].observer

    observer.on_model_loading(True)
    observer.on_model_loading(False)
    manager.stop()
    assert manager.wait_until_finished(5)

    session_id = "20261015_202358"
    assert broadcaster.of("model_loading") == [
        (session_id, {"loading": True}),
        (session_id, {"loading": False}),
    ]


def test_translations_are_published_as_translation_events(
    manager: SessionManager, factory: SessionFactory, broadcaster: RecordingBroadcaster
) -> None:
    manager.start(OPTIONS)
    observer = factory.sessions[0].observer

    observer.on_translation("system-000003", "en", "Good morning")
    manager.stop()
    assert manager.wait_until_finished(5)

    assert broadcaster.of("translation") == [
        (
            "20261015_202358",
            {"segment_id": "system-000003", "language": "en", "text": "Good morning"},
        )
    ]


class _ResumeJobs:
    """A `job_factory` for meetings the manager did not record: one step, then `done`."""

    def __init__(self, store: FileSessionRepository) -> None:
        self.store = store
        self.calls: list[tuple[str, bool, threading.Event | None]] = []
        self.fail_for: set[str] = set()

    def __call__(
        self, session_id: str, repair: bool, closed: threading.Event | None
    ) -> ProcessingJob:
        self.calls.append((session_id, repair, closed))
        if session_id in self.fail_for:
            raise RuntimeError("cannot build the job")

        def finished() -> None:
            meta = self.store.read_meta(session_id)
            self.store.write_meta(session_id, {**meta, "status": "done"})

        step = Step(StepKind.INDEX, 1.0, False, lambda token, progress: None)
        return ProcessingJob(session_id, (step,), on_finished=finished)


class _LiveSession:
    """Only what `resume_pending` reads of the session being recorded or stopped."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id


def test_resume_pending_orders_by_the_real_moment_not_the_text(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    # 23:30-03:00 is 02:30Z, later than 01:00+00:00 although its text sorts first
    later = _folder(store, "finalizing", capture_ended_at="2026-10-15T23:30:00-03:00")
    earlier = _folder(store, "finalizing", capture_ended_at="2026-10-16T01:00:00+00:00")
    broken = _folder(store, "finalizing", capture_ended_at="not a date")
    manager, _ = _resume_manager(factory, store, broadcaster)

    assert manager.resume_pending() == [broken, earlier, later]
    assert manager.wait_until_finished(5)


def _resume_manager(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> tuple[SessionManager, _ResumeJobs]:
    jobs = _ResumeJobs(store)
    manager = make_manager(factory, store, broadcaster, jobs=jobs)  # type: ignore[arg-type]
    return manager, jobs


def _folder(store: FileSessionRepository, status: str, **meta: Any) -> str:
    return make_session_folder(store, status=status, **meta)


def test_resume_pending_enqueues_finalizing_sessions_with_capture_ended_oldest_first(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    late = _folder(store, "finalizing", capture_ended_at="2026-10-15T21:00:00-03:00")
    early = _folder(store, "finalizing", capture_ended_at="2026-10-15T20:10:00-03:00")
    _folder(store, "finalizing")  # crashed during capture: interrupted, not resumed
    _folder(store, "done", capture_ended_at="2026-10-15T20:00:00-03:00")
    _folder(store, "interrupted", capture_ended_at="2026-10-15T20:00:00-03:00")
    manager, jobs = _resume_manager(factory, store, broadcaster)

    resumed = manager.resume_pending()

    assert resumed == [early, late]
    assert jobs.calls == [(early, True, None), (late, True, None)]
    assert manager.wait_until_finished(5)
    assert [store.read_meta(i)["status"] for i in (early, late)] == ["done", "done"]
    assert manager.resume_pending() == []  # nothing left unfinished


def test_resume_pending_skips_live_queued_and_unreadable_sessions(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    queued = _folder(store, "finalizing", capture_ended_at="2026-10-15T20:10:00-03:00")
    live = _folder(store, "finalizing", capture_ended_at="2026-10-15T20:11:00-03:00")
    bad = store.paths(store.create(datetime(2026, 10, 1, 9, 0)))
    bad.meta.write_text("{not json", encoding="utf-8")
    manager, jobs = _resume_manager(factory, store, broadcaster)
    hold = threading.Event()
    step = Step(StepKind.INDEX, 1.0, False, lambda token, progress: hold.wait(5))
    manager._queue.enqueue(ProcessingJob(queued, (step,), on_finished=lambda: None))
    manager._session = _LiveSession(live)  # type: ignore[assignment]

    assert manager.resume_pending() == []
    manager._session = None

    hold.set()
    assert manager.wait_until_finished(5)
    assert jobs.calls == []


def test_resume_pending_requeues_a_meeting_whose_job_factory_raised_at_stop(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    jobs = _ResumeJobs(store)
    manager = make_manager(factory, store, broadcaster, jobs=jobs)  # type: ignore[arg-type]
    manager.start(OPTIONS)
    session_id = factory.sessions[0].id
    jobs.fail_for.add(session_id)
    manager.stop()
    assert manager.wait_until_finished(5)
    meta = store.read_meta(session_id)
    assert meta["status"] == "finalizing" and not manager._queue.contains(session_id)
    store.write_meta(session_id, {**meta, "capture_ended_at": "2026-10-15T20:25:00-03:00"})
    jobs.fail_for.clear()  # after the restart the job can be built

    assert manager.resume_pending() == [session_id]

    assert manager.wait_until_finished(5)
    assert store.read_meta(session_id)["status"] == "done"
    assert jobs.calls[-1] == (session_id, True, None)


def test_resume_pending_goes_on_when_one_job_cannot_be_built(
    factory: SessionFactory, store: FileSessionRepository, broadcaster: RecordingBroadcaster
) -> None:
    broken = _folder(store, "finalizing", capture_ended_at="2026-10-15T20:00:00-03:00")
    fine = _folder(store, "finalizing", capture_ended_at="2026-10-15T20:30:00-03:00")
    manager, jobs = _resume_manager(factory, store, broadcaster)
    jobs.fail_for.add(broken)

    assert manager.resume_pending() == [fine]
    assert manager.wait_until_finished(5)
