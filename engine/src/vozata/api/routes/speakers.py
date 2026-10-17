"""`GET`/`PUT /sessions/{id}/speakers` (phase 16): name the speakers of one session.

Names live only in `speakers.json`; the transcript files are never rewritten.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import Speakers, SpeakersUpdate

router = APIRouter(tags=["speakers"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/sessions/{session_id}/speakers", response_model=Speakers)
def get_speakers(session_id: str, c: Container) -> dict[str, Any]:
    return _speakers(c, session_id, _transcript_speakers(c, session_id))


@router.put("/sessions/{session_id}/speakers", response_model=Speakers)
def rename_speakers(session_id: str, body: SpeakersUpdate, c: Container) -> dict[str, Any]:
    known = _transcript_speakers(c, session_id)
    for speaker_id in body.speakers:
        if speaker_id not in known:
            raise ApiError(422, "unknown_speaker", id=speaker_id, allowed=", ".join(known))
    names = {speaker_id: entry.name for speaker_id, entry in body.speakers.items()}
    c.store.rename_speakers(session_id, names)
    return _speakers(c, session_id, known)


def _transcript_speakers(c: ApiContainer, session_id: str) -> list[str]:
    """Speaker ids of the best transcript, in order of first appearance in time."""
    c.store.read_meta(session_id)  # 404 for an unknown session
    segments = sorted(c.store.load_transcript(session_id), key=lambda segment: segment.start)
    return list(dict.fromkeys(segment.speaker_id for segment in segments))


def _speakers(c: ApiContainer, session_id: str, speaker_ids: list[str]) -> dict[str, Any]:
    names = c.store.speaker_names(session_id)
    return {
        "speakers": {
            speaker_id: {
                "name": names.get(speaker_id),
                "default_label": c.labeler.label(speaker_id),
            }
            for speaker_id in speaker_ids
        }
    }
