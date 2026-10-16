"""`python -m vozata record`: record until Ctrl+C, with `p` + Enter to pause or resume."""

from __future__ import annotations

import contextlib
import signal
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol, TextIO

from vozata.audio.devices import DeviceInfo
from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.domain import ConversationLanguage, SessionStatus
from vozata.ports import Localizer, SessionObserver
from vozata.session import SessionStartError

WAIT_SLICE = 0.2  # Windows only delivers Ctrl+C between waits


class Session(Protocol):
    status: SessionStatus | None

    @property
    def paths(self) -> Any: ...

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...


class SessionBuilder(Protocol):
    def __call__(
        self,
        settings: Settings,
        observer: SessionObserver,
        *,
        language: ConversationLanguage | None,
        mic_device: int | None,
        system_device: int | None,
    ) -> Session: ...


def _wait_until_interrupted() -> None:  # pragma: no cover - waits for a real Ctrl+C
    stop = threading.Event()
    while not stop.wait(WAIT_SLICE):
        pass


class _Controls:
    """Toggle pause from stdin lines on a background thread; serialized with stop()."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._lock = threading.Lock()

    def follow(self, lines: Iterable[str]) -> None:
        for line in lines:
            if line.strip().lower() != "p":
                continue
            with self._lock:
                if self._session.status is SessionStatus.RECORDING:
                    self._session.pause()
                elif self._session.status is SessionStatus.PAUSED:
                    self._session.resume()

    def stop(self) -> None:
        with self._lock:
            self._session.stop()


def run_record(
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build: SessionBuilder,
    *,
    language: ConversationLanguage | None,
    mic_device: int | None,
    system_device: int | None,
    stdin: TextIO,
    wait: Callable[[], None] = _wait_until_interrupted,
) -> int:
    t = localizer.t
    session = build(
        settings, console, language=language, mic_device=mic_device, system_device=system_device
    )
    console.say(t("cli.loading_model"))
    try:
        session.start()
    except SessionStartError as error:
        console.say(str(error))
        return 1
    console.say(t("cli.recording", folder=session.paths.root))
    console.say(t("cli.controls"))
    controls = _Controls(session)
    threading.Thread(target=controls.follow, args=(stdin,), name="controls", daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        wait()
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)  # finalization must not be cut
    try:
        controls.stop()
    finally:
        signal.signal(signal.SIGINT, previous)
    console.say(t("cli.saved", folder=session.paths.root))
    return 0


def print_devices(
    console: ConsoleObserver,
    localizer: Localizer,
    microphones: list[DeviceInfo],
    loopbacks: list[DeviceInfo],
    defaults: tuple[DeviceInfo, DeviceInfo],
) -> int:
    t = localizer.t
    default_ids = {device.id for device in defaults}
    for title, devices in (
        ("cli.devices.microphones", microphones),
        ("cli.devices.loopbacks", loopbacks),
    ):
        console.say(t(title))
        for device in devices:
            marker = f"  ({t('cli.devices.default')})" if device.id in default_ids else ""
            console.say(f"  {device.id:>3}  {device.name}{marker}")
    return 0
