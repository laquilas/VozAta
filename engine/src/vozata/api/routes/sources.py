"""A recorded meeting's audio sources (phase 66): `GET` / `POST /sessions/{id}/sources`,
`POST /sessions/{id}/sources/keep-selected`, `GET /sessions/{id}/sources/{source_id}/audio`."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.session_sources import SessionSources
from vozata.audio.pcm import wav_header

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


class SourceChoice(BaseModel):
    selected: list[str] = Field(max_length=64)


def _sources(c: ApiContainer) -> SessionSources:
    if c.sources is None:
        raise ApiError(503, "sources_unavailable")
    return c.sources


@router.get("/sessions/{session_id}/sources")
def list_sources(session_id: str, c: Container) -> dict[str, Any]:
    """The kept sources (`[]` for a meeting recorded with one device per channel) and the day
    they are pruned (`kept_until`, null: kept)."""
    return _sources(c).describe(session_id)


@router.post("/sessions/{session_id}/sources", status_code=status.HTTP_202_ACCEPTED)
def choose_sources(session_id: str, body: SourceChoice, c: Container) -> None:
    """Use `selected` for the meeting: its tracks are rebuilt and it is transcribed, its speakers
    identified and its minutes written again (`processing` events follow). Edits are lost."""
    _sources(c).apply(session_id, set(body.selected))


@router.post("/sessions/{session_id}/sources/keep-selected")
def keep_selected(session_id: str, c: Container) -> dict[str, list[str]]:
    """Delete the files of the sources not selected now; `{removed: [ids]}`."""
    return {"removed": _sources(c).keep_only_selected(session_id)}


@router.get(
    "/sessions/{session_id}/sources/{source_id}/audio",
    responses={200: {"content": {"audio/wav": {}}, "description": "The source as a WAV file."}},
)
def source_audio(session_id: str, source_id: str, c: Container) -> Response:
    """One kept source as 16-bit mono WAV, to listen to it before choosing."""
    pcm, rate = _sources(c).frames(session_id, source_id)
    return Response(wav_header(rate, 1, len(pcm) // 2) + pcm, media_type="audio/wav")
