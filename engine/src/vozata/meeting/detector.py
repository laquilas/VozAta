"""Suggest recording when a meeting app is in a call (phase 54).

The detector polls which apps have an *active* audio session (Teams, Zoom… keep theirs inactive
while idle). A known app active for two polls in a row while nothing records is announced once;
it is announced again only after that app has been quiet for a minute. It never starts a
recording: consent stays with the user.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from vozata.config import Settings
from vozata.ports import AudioSessionMonitor

POLLS_NEEDED = 2  # a notification sound lasts less than two polls
QUIET_SECONDS = 60.0  # this long without audio ends the call
NAMES = {
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "ciscocollabhost.exe": "Webex",
    "webex.exe": "Webex",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
}

_log = logging.getLogger(__name__)


def parse_apps(text: str) -> tuple[str, ...]:
    """`MEETING_APPS` as lower-case executable names, in order, without blanks or repeats."""
    names = (part.strip().lower() for part in text.split(","))
    return tuple(dict.fromkeys(name for name in names if name))


def display_name(app: str) -> str:
    """The name the user knows: "Microsoft Teams" for `ms-teams.exe`, else the file name."""
    stem = app.removesuffix(".exe")
    return NAMES.get(app, stem[:1].upper() + stem[1:])


class MeetingDetector:
    """`poll()` once; `start()` polls every `MEETING_POLL_SECONDS` on a daemon thread. The
    settings are read on every poll, so the switch and the app list apply at once."""

    def __init__(
        self,
        monitor: AudioSessionMonitor,
        settings: Callable[[], Settings],
        recording: Callable[[], bool],
        publish: Callable[[str, str], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._monitor = monitor
        self._settings = settings
        self._recording = recording
        self._publish = publish
        self._clock = clock
        self._streak: dict[str, int] = {}
        self._last_active: dict[str, float] = {}
        self._suggested: set[str] = set()
        self._failed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll(self) -> None:
        settings = self._settings()
        if not settings.meeting_detection:
            self._streak.clear()
            return
        apps = set(parse_apps(settings.meeting_apps))
        active = self._active() & apps
        now = self._clock()
        for app in apps:
            if app in active:
                self._streak[app] = self._streak.get(app, 0) + 1
                self._last_active[app] = now
            else:
                self._streak[app] = 0
        for app in list(self._suggested):
            if app not in active and now - self._last_active.get(app, now) >= QUIET_SECONDS:
                self._suggested.discard(app)  # the call ended
        if self._recording():
            self._suggested |= active  # being recorded: no suggestion after Stop in this call
            return
        for app in sorted(active):
            if self._streak[app] >= POLLS_NEEDED and app not in self._suggested:
                self._suggested.add(app)
                self._publish(app, display_name(app))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="meeting-detector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def stopped(self) -> bool:
        return self._thread is None or not self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception:
                _log.exception("Meeting app detection failed")
            self._stop.wait(self._settings().meeting_poll_seconds)

    def _active(self) -> set[str]:
        try:
            names = self._monitor.active_apps()
        except Exception as error:
            if not self._failed:  # once: the audio service may stay broken for a while
                _log.warning("Could not read the audio sessions: %s", error)
                self._failed = True
            return set()
        return {name.lower() for name in names}
