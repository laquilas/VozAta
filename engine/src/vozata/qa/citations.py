"""Citations in an answer: `[session_id@hh:mm:ss]` mapped to the cited segment (phase 24).

Models are not always tidy, so a bracket may hold several citations (`[a@00:01:02, a@00:03:04]`)
and an item without a session id takes the previous one in the bracket, or the only session of
the context. Malformed times, unknown sessions and times before a session's first context
segment are ignored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from vozata.domain import Citation, TranscriptSegment

_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_ITEM = re.compile(r"(?:(\d{8}_\d{6}(?:_[1-9]\d*)?)\s*@\s*)?\b(\d{1,3}):(\d{2}):(\d{2})\b")


def parse_citations(
    text: str, sessions: Mapping[str, Sequence[TranscriptSegment]]
) -> list[Citation]:
    """Distinct citations in order of appearance, each mapped to a segment of `sessions`."""
    only = next(iter(sessions)) if len(sessions) == 1 else None
    citations: list[Citation] = []
    for bracket in _BRACKET.finditer(text):
        session_id = only
        for item in _ITEM.finditer(bracket.group(1)):
            session_id = item.group(1) or session_id
            hours, minutes, seconds = (int(item.group(n)) for n in (2, 3, 4))
            if session_id not in sessions or minutes > 59 or seconds > 59:
                continue
            segment = _segment_at(sessions[session_id], hours * 3600 + minutes * 60 + seconds)
            if segment is None:
                continue
            citation = Citation(session_id, segment.segment_id, segment.start)
            if citation not in citations:
                citations.append(citation)
    return citations


def _segment_at(segments: Sequence[TranscriptSegment], seconds: int) -> TranscriptSegment | None:
    """The last segment whose displayed time (`hh:mm:ss`, rounded down) is at or before it."""
    found = None
    for segment in sorted(segments, key=lambda s: s.start):
        if int(segment.start) > seconds:
            break
        found = segment
    return found
