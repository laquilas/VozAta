"""`GET /search` (phase 22): full-text search across every session's transcript."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import SearchResults
from vozata.labels import SpeakerLabeler

router = APIRouter(tags=["search"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/search", response_model=SearchResults)
def search(
    c: Container,
    q: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Best matches first; `snippet` marks each match with `\\u0002` ... `\\u0003`."""
    if c.search_index is None:
        return {"hits": []}
    hits = c.search_index.search(q, limit)
    labelers: dict[str, SpeakerLabeler] = {}
    for hit in hits:
        if hit.session_id not in labelers:  # names from each session's `speakers.json` (16)
            labelers[hit.session_id] = c.labeler.with_names(c.store.speaker_names(hit.session_id))
    return {
        "hits": [
            {**hit.to_dict(), "label": labelers[hit.session_id].label(hit.speaker_id)}
            for hit in hits
        ]
    }
