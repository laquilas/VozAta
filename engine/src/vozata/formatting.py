"""Timestamps and transcript line rendering."""

from __future__ import annotations

from collections.abc import Sequence

from vozata.domain import TranscriptSegment


def format_timestamp(seconds: float) -> str:
    """`hh:mm:ss`, rounded down; hours keep counting past 24; negatives clamp to zero."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def split_lines(lines: Sequence[str], max_chars: int) -> list[str]:
    """Group whole lines into parts of at most `max_chars` (a longer line stands alone)."""
    parts: list[list[str]] = []
    size = 0
    for line in lines:
        if parts and size + 1 + len(line) <= max_chars:
            parts[-1].append(line)
            size += 1 + len(line)
        else:
            parts.append([line])
            size = len(line)
    return ["\n".join(part) for part in parts]


def render_line(segment: TranscriptSegment, label: str) -> str:
    """`[hh:mm:ss] Label: text` as written to `transcript.md` and the console."""
    return f"[{format_timestamp(segment.start)}] {label}: {segment.text.strip()}"
