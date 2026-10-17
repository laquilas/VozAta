"""Give system segments the speakers found by a `Diarizer` (architecture §11)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from vozata.domain import Channel, SpeakerTurn, TranscriptSegment, Word

_Part = tuple[TranscriptSegment, int | None]  # a segment and the diarizer's speaker index


def assign_speakers(
    segments: Sequence[TranscriptSegment], turns: Sequence[SpeakerTurn]
) -> list[TranscriptSegment]:
    """System segments tagged `system:<n>`; microphone segments are returned unchanged.

    Each word gets the turn it overlaps most; words in a gap between turns stay with the previous
    speaker (leading ones with the first). A segment whose words change speaker is split at word
    boundaries (`<id>-1`, `<id>-2`, ...). A segment no turn overlaps keeps `system`. Speakers are
    numbered by their first appearance in the transcript.
    """
    parts: list[_Part] = []
    for segment in segments:
        if segment.channel is Channel.SYSTEM and turns:
            parts.extend(_split(segment, turns))
        else:
            parts.append((segment, None))
    numbers: dict[int, int] = {}
    for _segment, index in sorted(parts, key=lambda part: part[0].start):
        if index is not None and index not in numbers:
            numbers[index] = len(numbers) + 1
    return [
        segment if index is None else replace(segment, speaker_id=f"system:{numbers[index]}")
        for segment, index in parts
    ]


def _split(segment: TranscriptSegment, turns: Sequence[SpeakerTurn]) -> list[_Part]:
    if not segment.words:
        return [(segment, _best(turns, segment.start, segment.end))]
    speakers = _fill([_best(turns, word.start, word.end) for word in segment.words])
    if speakers is None:
        return [(segment, None)]
    runs: list[tuple[int, list[Word]]] = []
    for word, speaker in zip(segment.words, speakers, strict=True):
        if runs and runs[-1][0] == speaker:
            runs[-1][1].append(word)
        else:
            runs.append((speaker, [word]))
    if len(runs) == 1:
        return [(segment, runs[0][0])]
    return [
        (
            replace(
                segment,
                segment_id=f"{segment.segment_id}-{number}",
                start=words[0].start,
                end=words[-1].end,
                text=" ".join(word.text for word in words),
                words=tuple(words),
            ),
            speaker,
        )
        for number, (speaker, words) in enumerate(runs, start=1)
    ]


def _best(turns: Sequence[SpeakerTurn], start: float, end: float) -> int | None:
    """The speaker of the turn overlapping `start`-`end` most (containing it, if zero-length)."""
    if end <= start:
        inside = [turn for turn in turns if turn.start <= start < turn.end]
        return inside[0].speaker_index if inside else None
    best = max(turns, key=lambda turn: turn.overlap(start, end))
    return best.speaker_index if best.overlap(start, end) > 0 else None


def _fill(speakers: list[int | None]) -> list[int] | None:
    """Unassigned words take the previous speaker (leading ones the first); None if all are."""
    known = [speaker for speaker in speakers if speaker is not None]
    if not known:
        return None
    filled: list[int] = []
    current = known[0]
    for speaker in speakers:
        current = current if speaker is None else speaker
        filled.append(current)
    return filled
