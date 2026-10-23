from __future__ import annotations

import sys
from typing import Any

import pytest

from vozata import bootstrap
from vozata.config import Settings
from vozata.meeting.detector import MeetingDetector


class _Broadcaster:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, dict[str, Any]]] = []

    def publish(self, kind: str, session_id: str | None, data: dict[str, Any]) -> None:
        self.events.append((kind, session_id, data))


class _Monitor:
    def active_apps(self) -> set[str]:
        return {"Zoom.exe"}


def test_a_detected_call_is_published_as_a_meeting_detected_event() -> None:
    broadcaster = _Broadcaster()
    detector = bootstrap.build_meeting_detector(
        Settings,
        lambda: False,
        broadcaster,
        monitor=_Monitor(),  # type: ignore[arg-type]
    )
    assert isinstance(detector, MeetingDetector)

    detector.poll()
    detector.poll()

    assert broadcaster.events == [("meeting_detected", None, {"app": "zoom.exe", "name": "Zoom"})]


def test_the_windows_monitor_is_the_default_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from vozata.audio.sessions import WindowsAudioSessions

    monkeypatch.setattr(sys, "platform", "win32")

    detector = bootstrap.build_meeting_detector(Settings, lambda: False, _Broadcaster())  # type: ignore[arg-type]

    assert isinstance(detector, MeetingDetector)
    assert isinstance(detector._monitor, WindowsAudioSessions)


def test_there_is_no_detector_outside_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    assert bootstrap.build_meeting_detector(Settings, lambda: False, _Broadcaster()) is None  # type: ignore[arg-type]
