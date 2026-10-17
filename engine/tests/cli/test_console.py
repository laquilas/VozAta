from __future__ import annotations

import io
import threading

import pytest

from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver, meter_bar
from vozata.domain import Channel, ConversationLanguage, SessionStatus, TranscriptSegment
from vozata.labels import SpeakerLabeler


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Clock:
    def __init__(self) -> None:
        self.time = 100.0

    def __call__(self) -> float:
        return self.time


def _console(stream: io.StringIO, clock: _Clock | None = None) -> ConsoleObserver:
    localizer = FakeLocalizer()
    return ConsoleObserver(localizer, SpeakerLabeler(localizer), stream, clock or _Clock())


def _segment(text: str = "Hello.") -> TranscriptSegment:
    return TranscriptSegment("mic-000001", Channel.MIC, "mic", 65.0, 66.0, text, ())


@pytest.mark.parametrize(
    ("db", "bar"),
    [
        (-90.0, "[........]"),
        (-60.0, "[........]"),
        (-30.0, "[####....]"),
        (0.0, "[########]"),
        (6.0, "[########]"),
    ],
)
def test_meter_bar_maps_minus_60_to_0_dbfs_onto_8_cells(db: float, bar: str) -> None:
    assert meter_bar(db) == bar


def test_redirected_output_gets_plain_lines_without_a_meter() -> None:
    stream = io.StringIO()
    console = _console(stream)

    console.on_status(SessionStatus.RECORDING, 0.0)
    console.on_level(Channel.MIC, -10.0)
    console.on_segment(_segment())

    assert stream.getvalue() == "[00:01:05] labels.mic: Hello.\n"


def test_terminal_meter_shows_time_labels_and_levels() -> None:
    stream, clock = _Terminal(), _Clock()
    console = _console(stream, clock)
    console.on_status(SessionStatus.RECORDING, 0.0)
    clock.time += 3725

    console.on_level(Channel.MIC, -30.0)

    assert stream.getvalue() == "\r01:02:05  labels.mic [####....]  labels.system [........]"


def test_meter_redraws_at_most_every_200_ms() -> None:
    stream, clock = _Terminal(), _Clock()
    console = _console(stream, clock)
    console.on_status(SessionStatus.RECORDING, 0.0)

    console.on_level(Channel.MIC, -30.0)
    clock.time += 0.1
    console.on_level(Channel.MIC, 0.0)
    first = stream.getvalue()
    clock.time += 0.15
    console.on_level(Channel.SYSTEM, 0.0)

    assert first.count("\r") == 1
    assert stream.getvalue().endswith("labels.mic [########]  labels.system [########]")


def test_lines_clear_the_meter_and_redraw_it_below() -> None:
    stream = _Terminal()
    console = _console(stream)
    console.on_status(SessionStatus.RECORDING, 0.0)
    console.on_level(Channel.MIC, -60.0)
    meter = "00:00:00  labels.mic [........]  labels.system [........]"

    console.on_segment(_segment())

    assert stream.getvalue() == (
        f"\r{meter}\r{' ' * len(meter)}\r[00:01:05] labels.mic: Hello.\n\r{meter}"
    )


def test_status_messages_for_pause_resume_and_finalizing() -> None:
    stream, clock = _Terminal(), _Clock()
    console = _console(stream, clock)

    console.on_status(SessionStatus.RECORDING, 0.0)
    console.on_status(SessionStatus.PAUSED, 1.0)
    clock.time += 1
    console.on_level(Channel.MIC, -60.0)
    console.on_status(SessionStatus.RECORDING, 2.0)
    console.on_status(SessionStatus.FINALIZING, 3.0)
    console.on_level(Channel.MIC, -60.0)
    console.on_status(SessionStatus.DONE, 3.0)

    text = stream.getvalue()
    assert "cli.paused\n" in text and "cli.paused_marker" in text
    assert "cli.resumed\n" in text
    assert text.endswith("cli.finalizing\n")  # the meter stops once finalizing starts


def test_language_minutes_and_errors_are_printed() -> None:
    stream = io.StringIO()
    console = _console(stream)

    console.on_language_detected(ConversationLanguage.PT)
    console.on_minutes_ready("20261015_202358")
    console.on_action_items_ready("20261015_202358", 3)
    console.on_speakers_relabeled("20261015_202358")  # nothing to print
    console.on_error("minutes_failed", "Ollama is offline")
    console.say("Saved")

    assert stream.getvalue().splitlines() == [
        "cli.language_detected(language=languages.pt)",
        "cli.minutes_ready",
        "cli.action_items_ready(count=3)",
        "Ollama is offline",
        "Saved",
    ]


def test_events_from_many_threads_never_interleave_within_a_line() -> None:
    stream = io.StringIO()
    console = _console(stream)

    def emit() -> None:
        for _ in range(200):
            console.on_segment(_segment("x" * 50))

    threads = [threading.Thread(target=emit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = stream.getvalue().splitlines()
    assert len(lines) == 800
    assert set(lines) == {"[00:01:05] labels.mic: " + "x" * 50}


def test_interim_text_is_not_printed() -> None:
    stream = io.StringIO()

    _console(stream).on_partial(Channel.MIC, "mic", 1.0, "Hel")

    assert stream.getvalue() == ""


def test_model_loading_is_announced_while_recording() -> None:
    stream = io.StringIO()
    console = _console(stream)

    console.on_model_loading(True)
    console.on_model_loading(False)

    assert stream.getvalue().splitlines() == ["cli.loading_model", "cli.model_ready"]


def test_translations_are_printed_indented_under_their_line() -> None:
    stream = io.StringIO()
    console = _console(stream)

    console.on_translation("mic-000001", "pt", "Bom dia")

    assert stream.getvalue() == "    (pt) Bom dia\n"
