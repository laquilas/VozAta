"""Apply user text corrections to a transcript (phase 21); pure, no I/O."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vozata.domain import TranscriptSegment


@dataclass(frozen=True)
class SegmentEdit:
    """The text the user wants for one segment."""

    segment_id: str
    text: str


class UnknownSegmentError(ValueError):
    """The edit names a segment that is not in the current transcript."""

    def __init__(self, segment_id: str) -> None:
        super().__init__(segment_id)
        self.segment_id = segment_id


class EmptySegmentTextError(ValueError):
    """The edit would leave a segment without text."""

    def __init__(self, segment_id: str) -> None:
        super().__init__(segment_id)
        self.segment_id = segment_id


def apply_edits(
    segments: Sequence[TranscriptSegment], edits: Iterable[SegmentEdit]
) -> list[TranscriptSegment]:
    """The full transcript with `edits` applied, in its original order.

    A segment whose text changes gets `edited=True` and no words (their timings and confidence no
    longer match the text); unchanged segments are kept as they are. Every edit is validated before
    anything is applied. When an id appears twice, the last edit wins.
    """
    known = {segment.segment_id for segment in segments}
    texts: dict[str, str] = {}
    for edit in edits:
        if edit.segment_id not in known:
            raise UnknownSegmentError(edit.segment_id)
        text = edit.text.strip()
        if not text:
            raise EmptySegmentTextError(edit.segment_id)
        texts[edit.segment_id] = text
    return [_edited(segment, texts.get(segment.segment_id)) for segment in segments]


def _edited(segment: TranscriptSegment, text: str | None) -> TranscriptSegment:
    if text is None or text == segment.text.strip():
        return segment
    return dataclasses.replace(segment, text=text, words=(), edited=True)
