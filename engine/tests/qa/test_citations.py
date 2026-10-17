from __future__ import annotations

from vozata.domain import Channel, Citation, TranscriptSegment
from vozata.qa.citations import parse_citations

FIRST = "20261015_202358"
SECOND = "20261016_090000"


def segment(segment_id: str, start: float) -> TranscriptSegment:
    return TranscriptSegment(segment_id, Channel.MIC, "mic", start, start + 4, "text", ())


SESSIONS = {
    FIRST: (segment("mic-000001", 62.7), segment("mic-000002", 125.2)),
    SECOND: (segment("mic-000009", 3600.0),),
}


def test_valid_citations_map_to_the_segment_shown_at_that_time() -> None:
    text = f"Alice owns it [{FIRST}@00:02:05]. It ships in May [{SECOND}@01:00:00]."

    assert parse_citations(text, SESSIONS) == [
        Citation(FIRST, "mic-000002", 125.2),
        Citation(SECOND, "mic-000009", 3600.0),
    ]


def test_an_approximate_time_maps_to_the_segment_at_or_before_it() -> None:
    assert parse_citations(f"[{FIRST}@00:01:30]", SESSIONS) == [Citation(FIRST, "mic-000001", 62.7)]


def test_duplicates_are_kept_once_in_order() -> None:
    text = f"[{SECOND}@01:00:00] and [{FIRST}@00:01:02] and again [{SECOND}@01:00:00]"

    assert [c.segment_id for c in parse_citations(text, SESSIONS)] == ["mic-000009", "mic-000001"]


def test_one_bracket_may_hold_several_citations() -> None:
    text = f"[{FIRST}@00:01:02, 00:02:05; {SECOND}@01:00:00]"

    assert [c.segment_id for c in parse_citations(text, SESSIONS)] == [
        "mic-000001",
        "mic-000002",
        "mic-000009",
    ]


def test_malformed_citations_are_ignored() -> None:
    text = (
        f"[{FIRST}@00:61:00] [{FIRST}@00:00:75] [{FIRST}@1:2] [{FIRST}] [note] "
        f"{FIRST}@00:01:02 [{FIRST}@00:00:10]"  # unbracketed; before the first segment
    )

    assert parse_citations(text, SESSIONS) == []


def test_unknown_sessions_are_ignored() -> None:
    assert parse_citations("[20990101_000000@00:01:02]", SESSIONS) == []


def test_a_bare_time_needs_a_single_session_context() -> None:
    single = {FIRST: SESSIONS[FIRST]}

    assert parse_citations("[00:02:05]", single) == [Citation(FIRST, "mic-000002", 125.2)]
    assert parse_citations("[00:02:05]", SESSIONS) == []
