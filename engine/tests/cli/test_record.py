from __future__ import annotations

import io
import signal
import threading
from pathlib import Path
from typing import Any

from tests.fakes import FakeLocalizer
from vozata.audio.devices import DeviceInfo
from vozata.cli.console import ConsoleObserver
from vozata.cli.record import _Controls, print_devices, run_record
from vozata.config import Settings
from vozata.domain import ConversationLanguage, SessionStatus
from vozata.labels import SpeakerLabeler
from vozata.session import SessionStartError


class _Paths:
    root = Path("recordings/20261015_202358")


class _FakeSession:
    def __init__(self, start_error: SessionStartError | None = None) -> None:
        self.status: SessionStatus | None = None
        self.paths = _Paths()
        self.calls: list[str] = []
        self._start_error = start_error
        self.paused_twice = threading.Event()

    def start(self) -> None:
        self.calls.append("start")
        if self._start_error is not None:
            raise self._start_error
        self.status = SessionStatus.RECORDING

    def pause(self) -> None:
        self.calls.append("pause")
        self.status = SessionStatus.PAUSED

    def resume(self) -> None:
        self.calls.append("resume")
        self.status = SessionStatus.RECORDING
        self.paused_twice.set()

    def stop(self) -> None:
        self.calls.append("stop")
        self.sigint_during_stop = signal.getsignal(signal.SIGINT)
        self.status = SessionStatus.DONE


class _Builder:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.kwargs: dict[str, Any] = {}

    def __call__(self, settings: Settings, observer: Any, **kwargs: Any) -> _FakeSession:
        self.observer = observer
        self.kwargs = kwargs
        return self.session


def _run(session: _FakeSession, stdin: str, wait: Any) -> tuple[int, str, _Builder]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    builder = _Builder(session)
    code = run_record(
        Settings(),
        console,
        localizer,
        builder,
        language=ConversationLanguage.PT,
        mic_device=9,
        system_device=None,
        stdin=io.StringIO(stdin),
        wait=wait,
    )
    return code, out.getvalue(), builder


def _interrupt() -> None:
    raise KeyboardInterrupt


def test_records_until_ctrl_c_then_stops_and_reports_the_folder() -> None:
    session = _FakeSession()

    code, out, builder = _run(session, "", _interrupt)

    assert code == 0
    assert session.calls == ["start", "stop"]
    assert builder.kwargs == {
        "language": ConversationLanguage.PT,
        "mic_device": 9,
        "system_device": None,
    }
    assert builder.observer is not None
    folder = Path("recordings/20261015_202358")
    assert out.splitlines() == [
        f"cli.recording(folder={folder})",
        "cli.controls",
        f"cli.saved(folder={folder})",
    ]


def test_ctrl_c_is_ignored_while_finalizing_and_restored_afterwards() -> None:
    session = _FakeSession()
    before = signal.getsignal(signal.SIGINT)

    _run(session, "", _interrupt)

    assert session.sigint_during_stop == signal.SIG_IGN
    assert signal.getsignal(signal.SIGINT) == before


def test_p_and_enter_toggles_pause_and_other_input_is_ignored() -> None:
    session = _FakeSession()

    def wait() -> None:
        assert session.paused_twice.wait(5)

    _run(session, "x\nP\n\n p \nq\n", wait)

    assert session.calls == ["start", "pause", "resume", "stop"]


def test_a_start_failure_prints_the_localized_error_and_exits_1() -> None:
    session = _FakeSession(SessionStartError("device_timeout", "The mic did not open"))

    code, out, _ = _run(session, "", _interrupt)

    assert code == 1
    assert out.splitlines() == ["The mic did not open"]
    assert session.calls == ["start"]


def test_print_devices_lists_ids_names_and_defaults() -> None:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    mic = DeviceInfo(9, "Headset Mic", 2, 48000, False)
    usb = DeviceInfo(3, "USB Mic", 1, 44100, False)
    loopback = DeviceInfo(10, "Speakers [Loopback]", 2, 48000, True)

    code = print_devices(console, localizer, [usb, mic], [loopback], (mic, loopback))

    assert code == 0
    assert out.getvalue().splitlines() == [
        "cli.devices.microphones",
        "    3  USB Mic",
        "    9  Headset Mic  (cli.devices.default)",
        "cli.devices.loopbacks",
        "   10  Speakers [Loopback]  (cli.devices.default)",
    ]


def test_p_after_the_session_ended_does_nothing() -> None:
    session = _FakeSession()
    session.status = SessionStatus.DONE

    _Controls(session).follow(["p"])

    assert session.calls == []


def test_a_build_failure_prints_the_localized_error_and_exits_1() -> None:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)

    def build(*args: Any, **kwargs: Any) -> _FakeSession:
        raise SessionStartError("audio_unavailable", "Windows audio did not respond.")

    code = run_record(
        Settings(),
        console,
        localizer,
        build,
        language=None,
        mic_device=None,
        system_device=None,
        stdin=io.StringIO(""),
        wait=_interrupt,
    )

    assert code == 1
    assert out.getvalue().splitlines() == ["Windows audio did not respond."]


def test_a_remote_speech_api_is_announced_before_recording() -> None:
    session = _FakeSession()
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    settings = Settings(
        stt_provider="openai_compatible", openai_stt_url="https://api.openai.com/v1"
    )

    run_record(
        settings, console, localizer, _Builder(session),
        language=None, mic_device=None, system_device=None, stdin=io.StringIO(""), wait=_interrupt,
    )  # fmt: skip

    assert out.getvalue().splitlines()[0] == "cli.remote_stt(host=api.openai.com)"
