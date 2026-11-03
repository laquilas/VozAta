from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from vozata.api.recorder_link import RecorderLink, start_options
from vozata.api.session_manager import NoActiveSessionError, SessionConflictError, StartOptions
from vozata.domain import ConversationLanguage, SessionStatus, TranslationTarget
from vozata.ports import SessionNotFoundError
from vozata.recorder.engine_link import LINK_FILE, read_link, write_link
from vozata.recorder.manifest import PAUSED, RECORDING, STOPPED, Manifest, live_dir, write_manifest

ZONE = timezone(timedelta(hours=-3))
NOW = datetime(2026, 11, 3, 10, 30, 0, tzinfo=ZONE)


class FakeSession:
    def __init__(self, options: StartOptions) -> None:
        assert options.attach is not None
        self.options = options
        self.id = options.attach.recording_id
        self.recorder_id = options.attach.recording_id
        self.status = SessionStatus.RECORDING
        self.ended_at: float | None = None

    def end_at(self, seconds: float) -> None:
        self.ended_at = seconds


class FakeManager:
    def __init__(self) -> None:
        self.current: Any = None
        self.started: list[StartOptions] = []
        self.deleted: list[str] = []
        self.calls: list[str] = []
        self.conflict = False
        self.stop_error: Exception | None = None

    def start(self, options: StartOptions) -> dict[str, Any]:
        if self.conflict or self.current is not None:
            raise SessionConflictError
        self.started.append(options)
        self.current = FakeSession(options)
        return {"id": self.current.id}

    def pause(self) -> dict[str, Any]:
        self.calls.append("pause")
        self.current.status = SessionStatus.PAUSED
        return {}

    def resume(self) -> dict[str, Any]:
        self.calls.append("resume")
        self.current.status = SessionStatus.RECORDING
        return {}

    def stop(self) -> dict[str, Any]:
        if self.stop_error is not None:
            raise self.stop_error
        self.calls.append("stop")
        return {}

    def delete(self, session_id: str) -> None:
        self.deleted.append(session_id)

    def summary(self, session: Any) -> dict[str, Any]:
        return {"id": session.id, "status": session.status.value}


class FakeStore:
    def __init__(self) -> None:
        self.metas: dict[str, dict[str, Any]] = {}

    def read_meta(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.metas:
            raise SessionNotFoundError(session_id)
        return self.metas[session_id]


class FakeRecorder:
    def __init__(self, live: Path) -> None:
        self.live = live
        self.calls: list[tuple[str, Any]] = []
        self.up = True
        self.fail: Exception | None = None

    def health(self) -> dict[str, Any] | None:
        return {"recorder": "ok"} if self.up else None

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start", body))
        recording(self.live, "20261103_103000", RECORDING, body.get("options"))
        return {"id": "20261103_103000", "status": RECORDING}

    def pause(self) -> dict[str, Any]:
        self.calls.append(("pause", None))
        return {}

    def resume(self) -> dict[str, Any]:
        self.calls.append(("resume", None))
        return {}

    def stop(self) -> dict[str, Any]:
        self.calls.append(("stop", None))
        return {}

    def update_options(self, options: dict[str, Any]) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        self.calls.append(("options", options))
        return {}


def recording(
    live: Path, recording_id: str, status: str, options: dict[str, Any] | None = None
) -> Path:
    folder = live / recording_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(
        id=recording_id,
        started_at="2026-11-03T10:15:00-03:00",
        sample_rate=16000,
        status=status,
        devices={"mic": {"id": 15, "name": "JBL mic"}},
        options=options or {},
        duration_seconds=42.5,
    )
    write_manifest(folder, manifest)
    return folder


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.live = live_dir(tmp_path)
        self.manager = FakeManager()
        self.store = FakeStore()
        self.recorder = FakeRecorder(self.live)
        self.templates = {"general", "daily"}
        self.link = RecorderLink(
            tmp_path,
            self.manager,
            self.store,  # type: ignore[arg-type]
            self.recorder,
            check_template=self.templates.__contains__,
            wall_clock=lambda: NOW,
            tick_seconds=0.01,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_live_recording_is_attached_with_its_options(rig: Rig) -> None:
    folder = recording(
        rig.live,
        "20261103_101500",
        RECORDING,
        {"language": "pt", "template": "daily", "title": " Weekly ", "vocabulary": ["VozAta"]},
    )

    rig.link.tick()

    options = rig.manager.started[0]
    assert options.attach is not None and options.attach.recording_id == "20261103_101500"
    assert options.attach.device_names[next(iter(options.attach.device_names))] == "JBL mic"
    assert (options.language, options.template, options.title) == (
        ConversationLanguage.PT,
        "daily",
        "Weekly",
    )
    assert options.vocabulary == ("VozAta",)
    assert options.live_transcription is None  # the setting decides
    assert read_link(folder) == "20261103_101500"
    assert rig.link.following() == "20261103_101500"


def test_pause_resume_and_stop_follow_the_manifest(rig: Rig) -> None:
    recording(rig.live, "20261103_101500", RECORDING)
    rig.link.tick()

    recording(rig.live, "20261103_101500", PAUSED)
    rig.link.tick()
    recording(rig.live, "20261103_101500", RECORDING)
    rig.link.tick()
    recording(rig.live, "20261103_101500", STOPPED)
    rig.link.tick()
    rig.link.tick()  # the stop is handed over once

    assert rig.manager.calls == ["pause", "resume", "stop"]
    assert rig.manager.current.ended_at == 42.5


def test_a_stop_already_under_way_is_fine(rig: Rig) -> None:
    recording(rig.live, "20261103_101500", RECORDING)
    rig.link.tick()
    rig.manager.stop_error = NoActiveSessionError()
    recording(rig.live, "20261103_101500", STOPPED)

    rig.link.tick()


def test_a_stopped_recording_the_engine_never_saw_is_replayed_audio_only(rig: Rig) -> None:
    recording(rig.live, "20261103_090000", STOPPED, {"live_transcription": True})

    rig.link.tick()

    assert rig.manager.started[0].live_transcription is False
    assert rig.manager.calls == ["stop"]  # replay it all, then the queue


def test_one_recording_at_a_time_and_none_while_the_slot_is_taken(rig: Rig) -> None:
    recording(rig.live, "20261103_090000", STOPPED)
    recording(rig.live, "20261103_101500", RECORDING)

    rig.link.tick()

    assert [o.attach.recording_id for o in rig.manager.started] == ["20261103_090000"]  # type: ignore[union-attr]


def test_a_conflict_is_tried_again_later(rig: Rig) -> None:
    folder = recording(rig.live, "20261103_101500", RECORDING)
    rig.manager.conflict = True

    rig.link.tick()

    assert read_link(folder) is None


def test_a_stored_recording_waits_for_its_ingest_step(rig: Rig) -> None:
    folder = recording(rig.live, "20261103_101500", STOPPED)
    write_link(folder, "20261103_101500", NOW)
    rig.store.metas["20261103_101500"] = {"status": "finalizing", "capture_ended_at": "x"}

    rig.link.tick()

    assert rig.manager.started == []


def test_a_meeting_left_by_a_dead_engine_is_rebuilt_with_its_title(rig: Rig) -> None:
    folder = recording(rig.live, "20261103_101500", RECORDING)
    write_link(folder, "20261103_101500", NOW)
    rig.store.metas["20261103_101500"] = {"status": "recording", "title": "Kept title"}

    rig.link.tick()

    assert rig.manager.deleted == ["20261103_101500"]
    assert rig.manager.started[0].title == "Kept title"


def test_a_link_to_a_deleted_meeting_is_left_alone(rig: Rig) -> None:
    folder = recording(rig.live, "20261103_101500", STOPPED)
    write_link(folder, "20261103_090000", NOW)

    rig.link.tick()
    rig.link.tick()

    assert rig.manager.started == []


def test_bad_options_fall_back_to_the_defaults(rig: Rig) -> None:
    recording(
        rig.live,
        "20261103_101500",
        RECORDING,
        {"language": "klingon", "template": "unknown", "title": 5, "vocabulary": "x"},
    )

    rig.link.tick()

    options = rig.manager.started[0]
    assert (options.language, options.template, options.title, options.vocabulary) == (
        None,
        None,
        None,
        (),
    )


def test_start_options_maps_every_key() -> None:
    options = start_options(
        {"translate_to": "en", "live_transcription": False, "title": "x" * 300}, live=True
    )

    assert options.translate_to is TranslationTarget.EN
    assert options.live_transcription is False
    assert options.title is None  # too long


def test_start_recording_asks_the_recorder_and_attaches_at_once(rig: Rig) -> None:
    summary = rig.link.start_recording({"mic_device_id": 15, "language": "pt", "title": "Daily"})

    assert rig.recorder.calls[0] == (
        "start",
        {"mic_device_id": 15, "options": {"language": "pt", "title": "Daily"}},
    )
    assert summary == {"id": "20261103_103000", "status": "recording"}


def test_start_recording_reports_a_taken_slot(rig: Rig) -> None:
    recording(rig.live, "20261103_090000", STOPPED)
    rig.link.tick()  # replaying an old recording holds the slot

    with pytest.raises(SessionConflictError):
        rig.link.start_recording({})


def test_controls_go_to_the_recorder(rig: Rig) -> None:
    rig.link.pause()
    rig.link.resume()
    rig.link.stop()

    assert [name for name, _ in rig.recorder.calls] == ["pause", "resume", "stop"]


def test_a_rename_is_mirrored_to_the_recording(rig: Rig) -> None:
    from vozata.recorder_client import RecorderUnavailableError

    rig.link.mirror_title("New")
    rig.recorder.fail = RecorderUnavailableError("down")
    rig.link.mirror_title("Newer")

    assert rig.recorder.calls == [("options", {"title": "New"})]


def test_linked_sessions_and_availability(rig: Rig) -> None:
    folder = recording(rig.live, "20261103_101500", STOPPED)
    recording(rig.live, "20261103_090000", STOPPED)
    write_link(folder, "20261103_101500", NOW)

    assert rig.link.linked_sessions() == {"20261103_101500"}
    assert rig.link.recorder_available()
    rig.recorder.up = False
    assert not rig.link.recorder_available()


def test_an_unreadable_manifest_or_link_is_skipped(rig: Rig) -> None:
    folder = rig.live / "20261103_101500"
    folder.mkdir(parents=True)
    (folder / "recording.json").write_text("{", encoding="utf-8")
    (folder / LINK_FILE).write_text("{", encoding="utf-8")

    rig.link.tick()

    assert read_link(folder) is None
    assert rig.manager.started == []


def test_the_background_thread_ticks_until_closed(rig: Rig) -> None:
    recording(rig.live, "20261103_101500", RECORDING)

    rig.link.start()
    for _ in range(200):
        if rig.manager.started:
            break
        __import__("time").sleep(0.01)
    rig.link.close()

    assert rig.manager.started


def test_a_done_meeting_whose_folder_stayed_is_cleaned_up_again(tmp_path: Path) -> None:
    cleaned: list[str] = []
    rig = Rig(tmp_path)
    rig.link._cleanup = cleaned.append
    folder = recording(rig.live, "20261103_101500", STOPPED)
    write_link(folder, "20261103_101500", NOW)
    rig.store.metas["20261103_101500"] = {"status": "done", "capture_ended_at": "x"}

    rig.link.tick()

    assert cleaned == ["20261103_101500"]
    assert rig.manager.started == []
