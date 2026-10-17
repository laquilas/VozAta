from __future__ import annotations

from vozata.diarization.assign import assign_speakers
from vozata.domain import Channel, SpeakerTurn, TranscriptSegment, Word


def _segment(
    segment_id: str, channel: Channel, *words: tuple[str, float, float]
) -> TranscriptSegment:
    items = tuple(Word(text, start, end, 0.9) for text, start, end in words)
    return TranscriptSegment(
        segment_id=segment_id,
        channel=channel,
        speaker_id=channel.value,
        start=items[0].start,
        end=items[-1].end,
        text=" ".join(word.text for word in items),
        words=items,
    )


def _system(segment_id: str, *words: tuple[str, float, float]) -> TranscriptSegment:
    return _segment(segment_id, Channel.SYSTEM, *words)


def _bare(segment_id: str, start: float, end: float) -> TranscriptSegment:
    """A system segment without word timestamps."""
    return TranscriptSegment(segment_id, Channel.SYSTEM, "system", start, end, "Hi there", ())


def test_a_segment_inside_one_turn_gets_that_speaker_and_keeps_everything_else() -> None:
    segment = _system("system-000001", ("Hello", 1.0, 1.4), ("all.", 1.5, 2.0))

    [result] = assign_speakers([segment], [SpeakerTurn(0.5, 3.0, 7)])

    assert result.speaker_id == "system:1"
    assert (result.segment_id, result.text, result.words) == (
        segment.segment_id,
        segment.text,
        segment.words,
    )


def test_partial_overlap_picks_the_turn_that_overlaps_each_word_most() -> None:
    segment = _system("system-000001", ("Good", 1.0, 1.6), ("morning.", 1.7, 2.4))
    turns = [SpeakerTurn(0.0, 1.2, 0), SpeakerTurn(1.2, 5.0, 1)]

    [result] = assign_speakers([segment], turns)

    assert result.speaker_id == "system:1"  # "Good" is mostly in the second turn


def test_a_segment_spanning_a_speaker_change_is_split_at_word_boundaries() -> None:
    segment = _system(
        "system-000004",
        ("Ready?", 1.0, 1.5),
        ("Yes,", 2.0, 2.3),
        ("let's", 2.4, 2.6),
        ("go.", 2.7, 3.0),
    )
    turns = [SpeakerTurn(0.8, 1.8, 0), SpeakerTurn(1.9, 3.2, 1)]

    first, second = assign_speakers([segment], turns)

    assert (first.segment_id, first.speaker_id, first.text) == (
        "system-000004-1",
        "system:1",
        "Ready?",
    )
    assert (first.start, first.end) == (1.0, 1.5)
    assert (second.segment_id, second.speaker_id, second.text) == (
        "system-000004-2",
        "system:2",
        "Yes, let's go.",
    )
    assert (second.start, second.end) == (2.0, 3.0)
    assert [word.text for word in second.words] == ["Yes,", "let's", "go."]


def test_words_in_a_gap_between_turns_stay_with_the_previous_speaker() -> None:
    segment = _system("system-000001", ("One", 1.0, 1.4), ("two", 2.0, 2.4), ("three", 3.0, 3.4))
    turns = [SpeakerTurn(0.9, 1.5, 0), SpeakerTurn(2.9, 4.0, 1)]

    first, second = assign_speakers([segment], turns)

    assert first.text == "One two"
    assert second.text == "three"


def test_leading_words_in_a_gap_join_the_first_assigned_speaker() -> None:
    segment = _system("system-000001", ("Well,", 1.0, 1.4), ("okay.", 2.0, 2.4))

    [result] = assign_speakers([segment], [SpeakerTurn(1.9, 3.0, 4)])

    assert result.speaker_id == "system:1"
    assert result.text == segment.text


def test_a_segment_no_turn_overlaps_keeps_the_system_speaker() -> None:
    segment = _system("system-000001", ("Hello", 5.0, 5.5))
    bare = _bare("system-000002", 9.0, 10.0)

    assert assign_speakers([segment, bare], [SpeakerTurn(0.0, 1.0, 0)]) == [segment, bare]


def test_without_turns_nothing_changes() -> None:
    segment = _system("system-000001", ("Hello", 5.0, 5.5))

    assert assign_speakers([segment], []) == [segment]


def test_a_segment_without_words_gets_the_turn_it_overlaps_most() -> None:
    bare = _bare("system-000001", 1.0, 3.0)
    turns = [SpeakerTurn(0.0, 1.5, 0), SpeakerTurn(1.5, 4.0, 1)]

    [result] = assign_speakers([bare], turns)

    assert result.speaker_id == "system:1"
    assert result.segment_id == "system-000001"


def test_zero_length_words_use_the_turn_that_contains_them() -> None:
    segment = _system("system-000001", ("Uh", 2.0, 2.0), ("yes", 2.1, 2.5))
    turns = [SpeakerTurn(0.0, 1.0, 0), SpeakerTurn(1.9, 3.0, 1)]

    [result] = assign_speakers([segment], turns)

    assert result.speaker_id == "system:1"
    assert result.text == segment.text


def test_speakers_are_numbered_by_first_appearance_in_the_transcript() -> None:
    early = _system("system-000001", ("First", 1.0, 1.5))
    late = _system("system-000002", ("Second", 5.0, 5.5))
    again = _system("system-000003", ("Third", 9.0, 9.5))
    turns = [SpeakerTurn(8.5, 10.0, 0), SpeakerTurn(0.5, 2.0, 3), SpeakerTurn(4.5, 6.0, 0)]

    result = assign_speakers([late, early, again], turns)  # input order is kept

    assert [segment.speaker_id for segment in result] == ["system:2", "system:1", "system:2"]


def test_speakers_that_never_say_a_transcribed_word_get_no_number() -> None:
    segment = _system("system-000001", ("Hello", 5.0, 5.5))
    turns = [SpeakerTurn(0.0, 1.0, 0), SpeakerTurn(4.0, 6.0, 1)]

    [result] = assign_speakers([segment], turns)

    assert result.speaker_id == "system:1"


def test_microphone_segments_are_never_touched() -> None:
    mic = _segment("mic-000001", Channel.MIC, ("Me", 1.0, 1.5), ("talking", 2.0, 2.5))
    turns = [SpeakerTurn(0.0, 1.8, 0), SpeakerTurn(1.8, 3.0, 1)]

    assert assign_speakers([mic], turns) == [mic]
