"""Timestamps and transcript line rendering."""

from __future__ import annotations

from vozata.domain import TranscriptSegment


def format_timestamp(seconds: float) -> str:
    """`hh:mm:ss`, rounded down; hours keep counting past 24; negatives clamp to zero."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_line(segment: TranscriptSegment, label: str) -> str:
    """`[hh:mm:ss] Label: text` as written to `transcript.md` and the console."""
    return f"[{format_timestamp(segment.start)}] {label}: {segment.text.strip()}"
