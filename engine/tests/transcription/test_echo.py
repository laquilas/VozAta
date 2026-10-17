from __future__ import annotations

import pytest

from tests.fakes import FakeTranscriptSink
from vozata.domain import Channel, TranscriptSegment, Word
from vozata.transcription.echo import EchoFilter, echo_score, normalize


class _Clock:
    def __init__(self) -> None:
        self.time = 0.0

    def __call__(self) -> float:
        return self.time


def _segment(
    channel: Channel, start: float, text: str, *, seconds_per_word: float = 0.4, words: bool = True
) -> TranscriptSegment:
    tokens = text.split()
    timed = tuple(
        Word(token, start + i * seconds_per_word, start + (i + 1) * seconds_per_word, 0.9)
        for i, token in enumerate(tokens)
    )
    end = start + len(tokens) * seconds_per_word
    return TranscriptSegment(
        segment_id=f"{channel.value}-{start}",
        channel=channel,
        speaker_id=channel.value,
        start=start,
        end=end,
        text=text,
        words=timed if words else (),
    )


def _mic(start: float, text: str, **options: object) -> TranscriptSegment:
    return _segment(Channel.MIC, start, text, **options)  # type: ignore[arg-type]


def _system(start: float, text: str, **options: object) -> TranscriptSegment:
    return _segment(Channel.SYSTEM, start, text, **options)  # type: ignore[arg-type]


class _Rig:
    def __init__(self, hold: float = 8.0, threshold: float = 0.85) -> None:
        self.clock = _Clock()
        self.sink = FakeTranscriptSink()
        self.dropped: list[TranscriptSegment] = []
        self.filter = EchoFilter(
            self.sink,
            similarity_threshold=threshold,
            hold_seconds=hold,
            clock=self.clock,
            on_dropped=self.dropped.append,
        )

    def texts(self) -> list[str]:
        return [f"{segment.channel.value}: {segment.text}" for segment in self.sink.segments]


ECHO = "We will ship the beta on Friday."


def test_normalize_lowercases_and_removes_punctuation() -> None:
    assert normalize("  Hello, World!  It's   FINE… ") == "hello world its fine"


def test_echo_score_is_the_share_of_mic_words_found_in_order() -> None:
    assert echo_score("We will ship the beta", "we WILL ship, the beta!") == 1.0
    assert echo_score("we will ship the beta", "the beta ship will we") < 0.5
    assert echo_score("", "anything") == 0.0
    assert echo_score("anything", "") == 0.0


def test_identical_overlapping_text_is_dropped() -> None:
    rig = _Rig()
    rig.filter.emit(_system(10.0, ECHO))
    rig.filter.emit(_mic(10.2, ECHO))

    rig.filter.close()

    assert rig.texts() == [f"system: {ECHO}"]
    assert rig.filter.dropped == 1
    assert [segment.text for segment in rig.dropped] == [ECHO]
    assert rig.sink.closed


def test_different_overlapping_text_is_kept_once_the_hold_expires() -> None:
    rig = _Rig(hold=8.0)
    rig.filter.emit(_system(10.0, ECHO))
    rig.filter.emit(_mic(10.2, "I think Monday works better for us."))

    rig.clock.time = 7.9
    rig.filter.tick()
    assert rig.texts() == [f"system: {ECHO}"]  # still held

    rig.clock.time = 8.0
    rig.filter.tick()

    assert rig.texts() == [f"system: {ECHO}", "mic: I think Monday works better for us."]
    assert rig.filter.dropped == 0


def test_matching_text_outside_the_time_window_is_kept() -> None:
    rig = _Rig()
    rig.filter.emit(_system(10.0, ECHO))
    rig.filter.emit(_mic(20.0, ECHO))  # the user repeats it ten seconds later

    rig.filter.close()

    assert rig.texts() == [f"system: {ECHO}", f"mic: {ECHO}"]
    assert rig.filter.dropped == 0


def test_a_system_segment_arriving_later_within_the_hold_drops_the_mic_segment() -> None:
    rig = _Rig(hold=8.0)
    rig.filter.emit(_mic(10.2, ECHO))
    rig.clock.time = 5.0
    rig.filter.emit(_system(10.0, ECHO))

    rig.clock.time = 20.0
    rig.filter.tick()

    assert rig.texts() == [f"system: {ECHO}"]
    assert rig.filter.dropped == 1


def test_a_system_segment_arriving_after_the_hold_is_too_late() -> None:
    rig = _Rig(hold=8.0)
    rig.filter.emit(_mic(10.2, ECHO))
    rig.clock.time = 9.0
    rig.filter.emit(_system(10.0, ECHO))  # releases the expired mic segment first

    assert rig.texts() == [f"mic: {ECHO}", f"system: {ECHO}"]
    assert rig.filter.dropped == 0


def test_flush_releases_held_segments_in_order() -> None:
    rig = _Rig()
    rig.filter.emit(_mic(1.0, "first thing"))
    rig.filter.emit(_mic(3.0, "second thing"))

    rig.filter.flush()

    assert rig.texts() == ["mic: first thing", "mic: second thing"]
    assert not rig.sink.closed
    rig.filter.flush()
    assert len(rig.sink.segments) == 2


def test_an_echo_split_across_two_system_segments_is_dropped() -> None:
    rig = _Rig()
    rig.filter.emit(_system(10.0, "We will ship"))
    rig.filter.emit(_system(11.2, "the beta on Friday."))
    rig.filter.emit(_mic(10.1, ECHO))

    rig.filter.close()

    assert rig.filter.dropped == 1


def test_a_partial_echo_where_the_user_talks_over_is_kept() -> None:
    rig = _Rig()
    rig.filter.emit(_system(10.0, ECHO))
    rig.filter.emit(_mic(10.0, "No wait we will not ship the beta before the review"))

    rig.filter.close()

    assert rig.filter.dropped == 0
    assert len(rig.sink.segments) == 2


def test_only_system_words_within_the_tolerance_are_compared() -> None:
    rig = _Rig()
    # One long system segment; only its last words overlap the short mic segment.
    rig.filter.emit(
        _system(0.0, "alpha beta gamma delta epsilon zeta eta theta okay", seconds_per_word=1.0)
    )
    rig.filter.emit(_mic(8.0, "okay"))
    rig.filter.emit(_mic(1.0, "theta"))  # matches a word, but far from where it was said

    rig.filter.close()

    assert rig.texts() == [
        "system: alpha beta gamma delta epsilon zeta eta theta okay",
        "mic: theta",
    ]


def test_segments_without_word_timings_use_the_segment_span() -> None:
    rig = _Rig()
    rig.filter.emit(_system(0.0, "an earlier remark", words=False))  # outside the window
    rig.filter.emit(_system(10.0, ECHO, words=False))
    rig.filter.emit(_mic(10.5, ECHO, words=False))

    rig.filter.close()

    assert rig.filter.dropped == 1


def test_old_system_segments_are_forgotten() -> None:
    rig = _Rig()
    rig.filter.emit(_system(0.0, ECHO))
    rig.filter.emit(_system(40.0, "something else entirely"))
    rig.filter.emit(_mic(0.0, ECHO))  # late mic segment: its echo source is no longer kept

    rig.filter.close()

    assert rig.filter.dropped == 0


def test_an_empty_mic_text_is_kept() -> None:
    rig = _Rig()
    rig.filter.emit(_system(10.0, ECHO))
    rig.filter.emit(_mic(10.0, "..."))

    rig.filter.close()

    assert rig.filter.dropped == 0


@pytest.mark.parametrize(("threshold", "dropped"), [(0.7, 1), (0.9, 0)])
def test_the_threshold_decides(threshold: float, dropped: int) -> None:
    rig = _Rig(threshold=threshold)
    rig.filter.emit(_system(10.0, "we will ship the beta on friday"))
    rig.filter.emit(_mic(10.0, "we will ship the beta on monday"))  # 6 of 7 words

    rig.filter.close()

    assert rig.filter.dropped == dropped


def test_without_a_callback_drops_are_only_counted() -> None:
    sink = FakeTranscriptSink()
    echo = EchoFilter(sink, similarity_threshold=0.85, hold_seconds=8.0)
    echo.emit(_system(10.0, ECHO))
    echo.emit(_mic(10.0, ECHO))

    echo.close()

    assert echo.dropped == 1
    assert [segment.channel for segment in sink.segments] == [Channel.SYSTEM]
