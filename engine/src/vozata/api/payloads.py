"""JSON shapes shared by routes and events (api-contract "Shapes")."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vozata.domain import TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionRepository
from vozata.session_title import stored_title


def segment_payload(segment: TranscriptSegment, labeler: SpeakerLabeler) -> dict[str, Any]:
    """`Segment`: the raw segment plus its display label (raw files never store labels)."""
    payload = segment.to_dict()
    payload["label"] = labeler.label(segment.speaker_id)
    payload["edited"] = segment.edited  # phase 21
    return payload


def session_summary(
    store: SessionRepository, session_id: str, live_duration: float | None = None
) -> dict[str, Any]:
    """`SessionSummary` from the metadata; `live_duration` for the session being recorded."""
    meta = store.read_meta(session_id)
    return {
        "id": session_id,
        "status": meta.get("status"),
        "started_at": meta.get("started_at"),
        "ended_at": meta.get("ended_at"),
        "duration_seconds": (live_duration if live_duration is not None else _duration(meta)),
        "language": meta.get("language"),
        "has_minutes": store.has_minutes(session_id),
        "title": stored_title(meta),  # phase 35
        "speaker_count": store.speaker_count(session_id),  # phase 36
        "has_action_items": bool(store.read_action_items(session_id)),
        "template": meta.get("template") if isinstance(meta.get("template"), str) else None,
    }


def _duration(meta: dict[str, Any]) -> float | None:
    """The recorded length; older or interrupted sessions fall back to start-to-end time."""
    if meta.get("duration_seconds") is not None:
        return float(meta["duration_seconds"])
    started, ended = meta.get("started_at"), meta.get("ended_at")
    if not started or not ended:
        return None
    return (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()
