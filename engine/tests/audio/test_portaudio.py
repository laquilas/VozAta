from __future__ import annotations

import threading

import pytest

from vozata.audio.portaudio import PortAudioThread


class _FakePyAudio:
    def __init__(self) -> None:
        self.created_on = threading.current_thread().name
        self.terminated_on: list[str] = []

    def terminate(self) -> None:
        self.terminated_on.append(threading.current_thread().name)


def test_pyaudio_is_created_and_calls_run_on_the_portaudio_thread() -> None:
    audio = PortAudioThread(_FakePyAudio)

    ran_on = audio.call(lambda: threading.current_thread().name)

    assert audio.pa.created_on == "portaudio"
    assert ran_on == "portaudio"
    audio.close()


def test_errors_raised_on_the_thread_reach_the_caller() -> None:
    audio = PortAudioThread(_FakePyAudio)

    def fail() -> None:
        raise OSError("Unanticipated host error")

    with pytest.raises(OSError, match="Unanticipated host error"):
        audio.call(fail)
    assert audio.call(lambda: 42) == 42  # the thread survives the error
    audio.close()


def test_a_hanging_call_times_out() -> None:
    release = threading.Event()
    audio = PortAudioThread(_FakePyAudio, timeout=0.05)

    with pytest.raises(TimeoutError):
        audio.call(lambda: release.wait(5))
    release.set()


def test_a_hanging_initialization_times_out() -> None:
    release = threading.Event()

    def hang() -> _FakePyAudio:
        release.wait(5)
        return _FakePyAudio()

    with pytest.raises(TimeoutError):
        PortAudioThread(hang, timeout=0.05)
    release.set()


def test_close_terminates_once_on_the_thread_and_ends_it() -> None:
    audio = PortAudioThread(_FakePyAudio)
    pa = audio.pa

    audio.close()
    audio.close()

    assert pa.terminated_on == ["portaudio"]
    audio._thread.join(1)
    assert not audio._thread.is_alive()


def test_close_gives_up_quickly_when_the_thread_is_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    audio = PortAudioThread(_FakePyAudio)
    monkeypatch.setattr("vozata.audio.portaudio.CLOSE_TIMEOUT", 0.05)
    audio._jobs.put((lambda: release.wait(5), [], threading.Event()))  # a hung open

    with pytest.raises(TimeoutError):
        audio.close()
    release.set()
