from __future__ import annotations

import pytest

from vozata.domain import Channel, TranscriptSegment
from vozata.formatting import format_timestamp, render_line


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (59.999, "00:00:59"),
        (83.12, "00:01:23"),
        (3600, "01:00:00"),
        (90061.5, "25:01:01"),
        (-2.0, "00:00:00"),
    ],
)
def test_format_timestamp(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_render_line_uses_segment_start_label_and_text() -> None:
    segment = TranscriptSegment("mic-1", Channel.MIC, "mic", 83.12, 87.9, " Ship it. ", ())

    assert render_line(segment, "Me") == "[00:01:23] Me: Ship it."
