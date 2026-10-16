"""What every export contains, localized and ready to render (phase 11)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from vozata.domain import Block, ExportDocument, Row, TranscriptSegment
from vozata.formatting import format_timestamp
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(.+)$")
_NUMBERED = re.compile(r"^(\d+)[.)]\s+(.+)$")
_EMPHASIS = re.compile(r"\*\*|__|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])")
_LANGUAGES = ("en", "pt", "es")


__all__ = ["Block", "ExportDocument", "Row", "build_document", "parse_blocks"]


def build_document(
    summary: Mapping[str, Any],
    minutes_markdown: str | None,
    segments: Sequence[TranscriptSegment],
    labeler: SpeakerLabeler,
    localizer: Localizer,
) -> ExportDocument:
    """`summary` is the session's `SessionSummary`; segments are `TranscriptSegment`s."""
    t = localizer.t
    started = summary.get("started_at")
    date = (
        datetime.fromisoformat(str(started)).strftime("%Y-%m-%d %H:%M")
        if started
        else str(summary["id"])
    )
    details = []
    if summary.get("duration_seconds") is not None:
        duration = format_timestamp(float(summary["duration_seconds"]))
        details.append(t("export.duration", value=duration))
    if summary.get("language") in _LANGUAGES:
        name = t(f"languages.{summary['language']}")  # lowercase in some languages
        details.append(t("export.language", value=name[:1].upper() + name[1:]))
    minutes = minutes_markdown.strip() if minutes_markdown and minutes_markdown.strip() else None
    ordered = sorted(segments, key=lambda segment: segment.start)
    return ExportDocument(
        title=t("export.title", date=date),
        details=details,
        minutes_title=t("export.minutes"),
        minutes_markdown=minutes,
        minutes_blocks=parse_blocks(minutes or ""),
        no_minutes=t("export.no_minutes"),
        transcript_title=t("export.transcript"),
        columns=(t("export.column_time"), t("export.column_speaker"), t("export.column_text")),
        rows=[
            Row(
                format_timestamp(segment.start),
                labeler.label(segment.speaker_id),
                segment.text.strip(),
            )
            for segment in ordered
        ],
    )


def parse_blocks(markdown: str) -> list[Block]:
    """The Markdown subset the minutes prompt produces; emphasis markers are dropped."""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            blocks.append(Block("p", " ".join(paragraph)))
            paragraph.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            end_paragraph()
        elif heading := _HEADING.match(line):
            end_paragraph()
            level = min(len(heading.group(1)), 3)
            blocks.append(Block(f"h{level}", _clean(heading.group(2))))
        elif bullet := _BULLET.match(line):
            end_paragraph()
            blocks.append(Block("bullet", _clean(bullet.group(1))))
        elif numbered := _NUMBERED.match(line):
            end_paragraph()
            blocks.append(Block("numbered", f"{numbered.group(1)}. {_clean(numbered.group(2))}"))
        else:
            paragraph.append(_clean(line))
    end_paragraph()
    return blocks


def _clean(text: str) -> str:
    return _EMPHASIS.sub("", text).strip()
