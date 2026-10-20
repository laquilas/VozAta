from __future__ import annotations

from vozata.domain import Channel, TranscriptSegment
from vozata.transcription.resume import ResumePoint, resume_points

CHANNELS = (Channel.MIC, Channel.SYSTEM)


def seg(segment_id: str, start: float, end: float) -> TranscriptSegment:
    channel = Channel(segment_id.split("-")[0])
    return TranscriptSegment(segment_id, channel, channel.value, start, end, "text", ())


def test_resume_points_from_existing_segments() -> None:
    assert resume_points([seg("mic-000012", 0, 40.5), seg("system-000003", 2, 30)], CHANNELS) == {
        Channel.MIC: ResumePoint(40.5, 13),
        Channel.SYSTEM: ResumePoint(30.0, 4),
    }


def test_resume_points_without_segments_start_at_zero() -> None:
    assert resume_points([], CHANNELS) == {
        Channel.MIC: ResumePoint(0.0, 1),
        Channel.SYSTEM: ResumePoint(0.0, 1),
    }


def test_resume_points_use_the_latest_end_and_the_highest_number_in_any_order() -> None:
    segments = [
        seg("mic-000007", 50.0, 52.0),  # echo hold: mic rows are not ordered by time
        seg("mic-000009", 40.0, 45.0),
        seg("mic-000008", 46.0, 48.0),
    ]

    assert resume_points(segments, [Channel.MIC]) == {Channel.MIC: ResumePoint(52.0, 10)}


def test_resume_points_ignore_ids_that_are_not_counters() -> None:
    odd = TranscriptSegment("imported-1", Channel.MIC, "mic", 1.0, 3.0, "text", ())

    assert resume_points([odd], [Channel.MIC]) == {Channel.MIC: ResumePoint(3.0, 1)}
