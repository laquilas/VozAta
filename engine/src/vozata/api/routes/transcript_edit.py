"""Transcript corrections (phase 21): `PUT /sessions/{id}/transcript` and `DELETE .../edits`."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import EditTranscript, TranscriptEdited
from vozata.domain import TranscriptSegment
from vozata.transcript_edits import (
    EmptySegmentTextError,
    SegmentEdit,
    UnknownSegmentError,
    apply_edits,
)

_log = logging.getLogger(__name__)
router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.put("/sessions/{session_id}/transcript", response_model=TranscriptEdited)
def edit_transcript(session_id: str, body: EditTranscript, c: Container) -> dict[str, Any]:
    """Write the best transcript with these texts to `transcript.edited.jsonl` (atomic)."""
    _check_editable(c, session_id)
    edits = [SegmentEdit(segment.segment_id, segment.text) for segment in body.segments]
    try:
        segments = apply_edits(c.store.load_transcript(session_id), edits)
    except UnknownSegmentError as error:
        raise ApiError(422, "unknown_segment", id=error.segment_id) from None
    except EmptySegmentTextError as error:
        raise ApiError(422, "empty_segment_text", id=error.segment_id) from None
    c.store.write_edited(session_id, segments)
    _reindex(c, session_id, segments)
    return {"source": "edited"}


@router.delete("/sessions/{session_id}/transcript/edits", status_code=status.HTTP_204_NO_CONTENT)
def revert_transcript(session_id: str, c: Container) -> Response:
    """Drop the user's edits; the transcript falls back to the diarized or raw file."""
    _check_editable(c, session_id)
    if c.store.delete_edited(session_id):
        _reindex(c, session_id, c.store.load_transcript(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _check_editable(c: ApiContainer, session_id: str) -> None:
    c.store.read_meta(session_id)  # 404 for an unknown session
    current = c.manager.current
    if current is not None and current.status is not None and current.id == session_id:
        raise ApiError(409, "transcript_still_recording", id=session_id)


def _reindex(c: ApiContainer, session_id: str, segments: list[TranscriptSegment]) -> None:
    """Keep search (22) in step with the edits; a failure never undoes a saved edit."""
    if c.search_index is None:
        return
    try:
        c.search_index.index_session(session_id, segments)
    except Exception:
        _log.exception("Could not reindex session %s after a transcript edit", session_id)
