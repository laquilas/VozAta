"""Where each channel's transcription resumes on a meeting whose transcript is partial.

`CarryOverStitcher` drops committed audio and carries the uncommitted tail, so a channel's last
committed segment `end` is exactly where the rest of its transcription starts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from vozata.domain import Channel, TranscriptSegment


@dataclass(frozen=True)
class ResumePoint:
    """`start`: session seconds to transcribe from; `next_index`: the channel's next id number."""

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
