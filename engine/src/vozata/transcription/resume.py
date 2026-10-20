"""Where each channel's transcription resumes on a meeting whose transcript is partial.

`CarryOverStitcher` drops committed audio and carries the uncommitted tail. A segment's `end` is
its last word's end, but the stitcher cuts up to `MAX_WORD_TAIL_SECONDS` later (through the
word's still-voiced tail, `voiced_end`) or halfway to the next word. `ResumePoint.start` is the
segment `end`, the lower bound from the transcript alone; `offline_feed.track_spans` moves it
past the voiced tail in the stored audio, as the live cut did, so no fragment is re-transcribed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vozata.domain import Channel, TranscriptSegment


@dataclass(frozen=True)
class ResumePoint:
    """`start`: the channel's last written `end` (session seconds; the voiced tail after it is
    skipped from the audio); `next_index`: the channel's next id number."""

    start: float
    next_index: int


def resume_points(
    segments: Sequence[TranscriptSegment], channels: Iterable[Channel]
) -> dict[Channel, ResumePoint]:
    """Each channel's latest raw segment `end` (0.0 without one) and its next id number."""
    points: dict[Channel, ResumePoint] = {}
    for channel in channels:
        own = [segment for segment in segments if segment.channel is channel]
        start = max((segment.end for segment in own), default=0.0)
        id_pattern = re.compile(rf"^{re.escape(channel.value)}-(\d+)$")
        numbers = [
            int(match.group(1))
            for segment in own
            if (match := id_pattern.match(segment.segment_id)) is not None
        ]
        points[channel] = ResumePoint(float(start), max(numbers, default=0) + 1)
    return points
