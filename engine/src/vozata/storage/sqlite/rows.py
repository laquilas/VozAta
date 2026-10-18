"""Rows of `vozata.db` to and from domain values: session metadata, segments, action items."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from vozata.domain import ActionItem, Channel, TranscriptSegment, Word
from vozata.ports import SessionNotFoundError
from vozata.storage.files.layout import SESSION_ID

# Metadata fields with a column of their own in `sessions` (the others live in `meta_json`).
TEXT_COLUMNS = (
    "status",
    "started_at",
    "ended_at",
    "last_heartbeat_at",
    "language",
    "language_source",
    "app_language",
    "template",
    "title",
)
META_COLUMNS = (*TEXT_COLUMNS, "duration_seconds")

SEGMENT_COLUMNS = 'segment_id, channel, speaker_id, start, "end", text, words_json, edited'
ACTION_ITEM_COLUMNS = "item_id, description, owner, due, source_ids_json, exported_url"


def check_id(session_id: str) -> None:
    """Session ids are `YYYYMMDD_HHMMSS[_n]` (also the audio folder name); others are unknown."""
    if not SESSION_ID.match(session_id):
        raise SessionNotFoundError(session_id)


def _in_column(key: str, value: Any) -> bool:
    """Whether `value` of `key` is stored in its column (it round-trips there unchanged)."""
    if key == "duration_seconds":
        return isinstance(value, float)  # an int would come back as a float (REAL column)
    return key in TEXT_COLUMNS and isinstance(value, str)


def meta_to_row(meta: dict[str, Any]) -> tuple[tuple[Any, ...], str]:
    """The column values (in `META_COLUMNS` order) and `meta_json`.

    `meta_json` keeps every key in order; a value stored in its column is `null` there, so
    `row_to_meta` gives back exactly the keys that were written.
    """
    columns = tuple(
        meta[key] if key in meta and _in_column(key, meta[key]) else None for key in META_COLUMNS
    )
    rest = {key: None if _in_column(key, value) else value for key, value in meta.items()}
    return columns, json.dumps(rest, ensure_ascii=False)


def row_to_meta(columns: Sequence[Any], meta_json: str) -> dict[str, Any]:
    """The metadata written by `meta_to_row` (`columns` in `META_COLUMNS` order)."""
    stored = dict(zip(META_COLUMNS, columns, strict=True))
    rest: dict[str, Any] = json.loads(meta_json)
    return {
        key: stored[key] if value is None and stored.get(key) is not None else value
        for key, value in rest.items()
    }


def segment_row(segment: TranscriptSegment) -> tuple[Any, ...]:
    """Values for `SEGMENT_COLUMNS`."""
    words = json.dumps([word.to_dict() for word in segment.words], ensure_ascii=False)
    return (
        segment.segment_id,
        segment.channel.value,
        segment.speaker_id,
        segment.start,
        segment.end,
        segment.text,
        words,
        int(segment.edited),
    )


def row_segment(row: Sequence[Any]) -> TranscriptSegment:
    """A segment from `SEGMENT_COLUMNS` values."""
    segment_id, channel, speaker_id, start, end, text, words_json, edited = row
    return TranscriptSegment(
        segment_id=segment_id,
        channel=Channel(channel),
        speaker_id=speaker_id,
        start=float(start),
        end=float(end),
        text=text,
        words=tuple(Word.from_dict(word) for word in json.loads(words_json)),
        edited=bool(edited),
    )


def action_item_row(item: ActionItem) -> tuple[Any, ...]:
    """Values for `ACTION_ITEM_COLUMNS`."""
    sources = json.dumps(list(item.source_segment_ids), ensure_ascii=False)
    return (item.id, item.description, item.owner, item.due, sources, item.exported_url)


def row_action_item(row: Sequence[Any]) -> ActionItem:
    item_id, description, owner, due, sources, exported_url = row
    return ActionItem(item_id, description, owner, due, tuple(json.loads(sources)), exported_url)
