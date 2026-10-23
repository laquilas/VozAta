from __future__ import annotations

import threading

import pytest

from vozata.config import Settings
from vozata.meeting.detector import MeetingDetector, display_name, parse_apps


class _Monitor:
    def __init__(self) -> None:
        self.active: set[str] = set()
        self.polls = 0

    def active_apps(self) -> set[str]:
        self.polls += 1
        return set(self.active)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Harness:
    def __init__(self, settings: Settings | None = None) -> None:
        self.monitor = _Monitor()
        self.clock = _Clock()
        self.recording = False
        self.settings = settings or Settings()
        self.published: list[tuple[str, str]] = []
        self.detector = MeetingDetector(
            self.monitor,
            lambda: self.settings,
            lambda: self.recording,
            lambda app, name: self.published.append((app, name)),
            clock=self.clock,
        )

    def poll(self, times: int = 1, every: float = 5.0) -> None:
        for _ in range(times):
            self.detector.poll()
            self.clock.now += every


def test_a_known_app_in_a_call_for_two_polls_is_suggested_once() -> None:
    h = _Harness()
    h.monitor.active = {"ms-teams.exe"}

    h.poll()
    assert h.published == []  # one poll could be a notification sound
    h.poll(5)

    assert h.published == [("ms-teams.exe", "Microsoft Teams")]


def test_a_short_sound_is_not_a_call() -> None:
    h = _Harness()
    h.monitor.active = {"slack.exe"}
    h.poll()
    h.monitor.active = set()
    h.poll()
    h.monitor.active = {"slack.exe"}
    h.poll()

    assert h.published == []


def test_unknown_apps_and_names_are_case_insensitive() -> None:
    h = _Harness()
    h.monitor.active = {"Spotify.exe", "ZOOM.EXE"}

    h.poll(2)

    assert h.published == [("zoom.exe", "Zoom")]


def test_the_same_call_is_suggested_again_only_after_a_quiet_minute() -> None:
    h = _Harness()
    h.monitor.active = {"Zoom.exe"}
    h.poll(2)
    h.monitor.active = set()
    h.poll(3)  # 15 s of quiet: a pause in the same call
    h.monitor.active = {"Zoom.exe"}
    h.poll(2)
    assert len(h.published) == 1

    h.monitor.active = set()
    h.poll(13)  # over a minute of quiet: the call ended
    h.monitor.active = {"Zoom.exe"}
    h.poll(2)

    assert len(h.published) == 2


def test_nothing_is_suggested_while_recording_nor_right_after_it_in_the_same_call() -> None:
    h = _Harness()
    h.recording = True
    h.monitor.active = {"ms-teams.exe"}
    h.poll(4)
    assert h.published == []
    assert h.monitor.polls == 4  # still watched, so Stop does not trigger a suggestion

    h.recording = False
    h.poll(4)

    assert h.published == []


def test_a_second_app_is_suggested_on_its_own() -> None:
    h = _Harness()
    h.monitor.active = {"ms-teams.exe"}
    h.poll(2)
    h.monitor.active = {"ms-teams.exe", "Discord.exe"}
    h.poll(2)

    assert h.published == [("ms-teams.exe", "Microsoft Teams"), ("discord.exe", "Discord")]


def test_the_switch_and_the_list_are_read_on_every_poll() -> None:
    h = _Harness(Settings(meeting_detection=False))
    h.monitor.active = {"ms-teams.exe"}
    h.poll(3)
    assert (h.published, h.monitor.polls) == ([], 0)  # off: nothing is even asked

    h.settings = Settings(meeting_apps="Telegram.exe")
    h.monitor.active = {"Telegram.exe"}
    h.poll(2)

    assert h.published == [("telegram.exe", "Telegram")]


def test_a_monitor_failure_is_no_call() -> None:
    class _Broken:
        def active_apps(self) -> set[str]:
            raise OSError("COM failed")

    published: list[tuple[str, str]] = []
    detector = MeetingDetector(
        _Broken(), Settings, lambda: False, lambda a, n: published.append((a, n))
    )

    detector.poll()
    detector.poll()

    assert published == []


@pytest.mark.parametrize(
    ("text", "apps"),
    [
        (" Zoom.exe , ms-teams.exe ,,", ("zoom.exe", "ms-teams.exe")),
        ("", ()),
        ("a.exe,A.EXE", ("a.exe",)),
    ],
)
def test_the_app_list_is_split_trimmed_and_lowercased(text: str, apps: tuple[str, ...]) -> None:
    assert parse_apps(text) == apps


@pytest.mark.parametrize(
    ("app", "name"),
    [
        ("ms-teams.exe", "Microsoft Teams"),
        ("teams.exe", "Microsoft Teams"),
        ("ciscocollabhost.exe", "Webex"),
        ("telegram.exe", "Telegram"),
        ("weird", "Weird"),
    ],
)
def test_display_names(app: str, name: str) -> None:
    assert display_name(app) == name


def test_the_thread_polls_until_stopped() -> None:
    polled = threading.Event()

    class _Signal:
        def active_apps(self) -> set[str]:
            polled.set()
            return set()

    detector = MeetingDetector(
        _Signal(), lambda: Settings(meeting_poll_seconds=1), lambda: False, lambda a, n: None
    )
    detector.start()
    try:
        assert polled.wait(5)
    finally:
        detector.stop()
    assert detector.stopped
