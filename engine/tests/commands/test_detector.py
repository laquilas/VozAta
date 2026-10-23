from __future__ import annotations

import logging

import pytest

from vozata.commands.detector import VoiceCommandSink
from vozata.commands.matcher import CommandMatcher
from vozata.domain import Channel, TranscriptSegment, VoiceCommand

MINUTES = VoiceCommand("gere a ata", "minutes")
DECIDED = VoiceCommand("o que foi decidido", "ask", "O que foi decidido?")


def _segment(start: float, text: str, channel: Channel = Channel.MIC) -> TranscriptSegment:
    return TranscriptSegment(
        f"{channel.value}-{int(start):06d}", channel, channel.value, start, start + 2, text, ()
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _sink() -> tuple[VoiceCommandSink, list[VoiceCommand], _Clock]:
    heard: list[VoiceCommand] = []
    clock = _Clock()
    sink = VoiceCommandSink(CommandMatcher("VozAta", [MINUTES, DECIDED]), heard.append, clock)
    return sink, heard, clock


def test_a_command_into_the_microphone_runs() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "Ok. VozAta, gere a ata."))

    assert heard == [MINUTES]


def test_the_system_audio_never_runs_a_command() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "VozAta, gere a ata.", Channel.SYSTEM))

    assert heard == []


def test_a_wake_word_alone_waits_for_the_next_microphone_segment() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "VozAta."))  # ends at 12
    sink.emit(_segment(14, "Bom dia.", Channel.SYSTEM))  # someone else in between
    sink.emit(_segment(16, "O que foi decidido?"))

    assert heard == [DECIDED]


def test_the_command_must_follow_soon() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "VozAta."))
    sink.emit(_segment(30, "Gere a ata."))

    assert heard == []


def test_after_a_wake_word_other_speech_cancels_the_wait() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "VozAta."))
    sink.emit(_segment(13, "Esquece."))
    sink.emit(_segment(15, "Gere a ata."))  # no wake word any more

    assert heard == []


def test_a_wake_word_with_other_words_does_not_wait() -> None:
    sink, heard, _ = _sink()

    sink.emit(_segment(10, "VozAta, bom dia."))
    sink.emit(_segment(12, "Gere a ata."))

    assert heard == []


def test_the_same_action_runs_once_per_cooldown() -> None:
    sink, heard, clock = _sink()

    sink.emit(_segment(10, "VozAta, gere a ata."))
    clock.now += 5
    sink.emit(_segment(15, "VozAta, gere a ata!"))
    sink.emit(_segment(17, "VozAta, o que foi decidido?"))  # another action is fine
    clock.now += 15
    sink.emit(_segment(40, "VozAta, gere a ata."))

    assert heard == [MINUTES, DECIDED, MINUTES]


def test_a_failing_command_never_stops_the_transcript(caplog: pytest.LogCaptureFixture) -> None:
    def broken(command: VoiceCommand) -> None:
        raise RuntimeError("boom")

    sink = VoiceCommandSink(CommandMatcher("VozAta", [MINUTES]), broken)

    with caplog.at_level(logging.ERROR):
        sink.emit(_segment(10, "VozAta, gere a ata."))
    sink.close()

    assert "Checking a voice command failed" in caplog.text
