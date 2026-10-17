from __future__ import annotations

import pytest

from vozata.domain import Channel, TranscriptSegment, Word
from vozata.transcript_edits import (
    EmptySegmentTextError,
    SegmentEdit,
    UnknownSegmentError,
    apply_edits,
)


def _segment(segment_id: str, text: str, start: float = 0.0) -> TranscriptSegment:
    word = Word(text.split()[0], start, start + 0.3, 0.4)
    return TranscriptSegment(segment_id, Channel.MIC, "mic", start, start + 1, text, (word,))


SEGMENTS = [_segment("mic-000001", "we ship on friday", 0.0), _segment("mic-000002", "ok", 2.0)]


def test_a_changed_segment_is_flagged_and_loses_its_words() -> None:
    result = apply_edits(SEGMENTS, [SegmentEdit("mic-000001", "We ship on Thursday")])

    assert result[0].text == "We ship on Thursday"
    assert result[0].edited is True
    assert result[0].words == ()
    assert (result[0].start, result[0].end, result[0].speaker_id) == (0.0, 1.0, "mic")
    assert result[1] == SEGMENTS[1]


def test_an_edit_with_the_same_text_keeps_the_segment_and_its_words() -> None:
    result = apply_edits(SEGMENTS, [SegmentEdit("mic-000002", "  ok ")])

    assert result == SEGMENTS


def test_new_text_is_trimmed() -> None:
    result = apply_edits(SEGMENTS, [SegmentEdit("mic-000002", "  okay\n")])

    assert result[1].text == "okay"


def test_no_edits_returns_the_transcript_unchanged() -> None:
    assert apply_edits(SEGMENTS, []) == SEGMENTS


def test_an_unknown_segment_id_is_rejected() -> None:
    with pytest.raises(UnknownSegmentError) as caught:
        apply_edits(SEGMENTS, [SegmentEdit("mic-999999", "text")])

    assert caught.value.segment_id == "mic-999999"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_text_is_rejected(text: str) -> None:
    with pytest.raises(EmptySegmentTextError) as caught:
        apply_edits(SEGMENTS, [SegmentEdit("mic-000001", text)])

    assert caught.value.segment_id == "mic-000001"


def test_the_last_edit_of_a_segment_wins() -> None:
    edits = [SegmentEdit("mic-000002", "first"), SegmentEdit("mic-000002", "second")]

    assert apply_edits(SEGMENTS, edits)[1].text == "second"


def test_an_already_edited_segment_stays_edited() -> None:
    once = apply_edits(SEGMENTS, [SegmentEdit("mic-000001", "fixed")])

    again = apply_edits(once, [SegmentEdit("mic-000001", "fixed")])

    assert again[0].edited is True
