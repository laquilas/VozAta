"""Session routes tagged 06: lifecycle of the current session, history, transcript, minutes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.payloads import segment_payload, session_summary
from vozata.api.routes.templates import check_template
from vozata.api.schemas import (
    Minutes,
    RegenerateMinutes,
    SessionDetail,
    SessionList,
    SessionSummary,
    StartSession,
    Transcript,
)
from vozata.api.session_manager import StartOptions
from vozata.domain import ConversationLanguage, TranslationTarget

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=SessionSummary)
def start_session(body: StartSession, c: Container) -> dict[str, Any]:
    check_template(c, body.template)
    options = StartOptions(
        language=ConversationLanguage(body.language) if body.language else None,
        mic_device=body.mic_device_id,
        system_device=body.system_device_id,
        template=body.template,
        vocabulary=tuple(body.vocabulary or ()),
        translate_to=TranslationTarget(body.translate_to) if body.translate_to else None,
    )
    try:
        return c.manager.start(options)
    except LookupError as error:  # an unknown device id
        raise ApiError(404, "device_not_found", reason=error) from None


@router.post("/sessions/current/pause", response_model=SessionSummary)
def pause_session(c: Container) -> dict[str, Any]:
    return c.manager.pause()


@router.post("/sessions/current/resume", response_model=SessionSummary)
def resume_session(c: Container) -> dict[str, Any]:
    return c.manager.resume()


@router.post(
    "/sessions/current/stop", status_code=status.HTTP_202_ACCEPTED, response_model=SessionSummary
)
def stop_session(c: Container) -> dict[str, Any]:
    return c.manager.stop()


@router.get("/sessions", response_model=SessionList)
def list_sessions(
    c: Container,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    ids = c.store.list_sessions()
    return {
        "items": [_summary(c, session_id) for session_id in ids[offset : offset + limit]],
        "total": len(ids),
    }


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def session_detail(session_id: str, c: Container) -> dict[str, Any]:
    meta = c.store.read_meta(session_id)
    detail = {**meta, **_summary(c, session_id)}
    folder = c.store.folder(session_id)
    if folder is not None:  # file backend
        detail["files"] = c.store.files(session_id)
        detail["folder"] = str(folder.resolve())
    return detail


@router.get("/sessions/{session_id}/transcript", response_model=Transcript)
def transcript(session_id: str, c: Container) -> dict[str, Any]:
    source, segments = c.store.load_transcript_with_source(session_id)
    ordered = sorted(segments, key=lambda segment: segment.start)
    labeler = c.labeler.with_names(c.store.speaker_names(session_id))
    translations = c.store.load_translations(session_id)
    payloads = []
    for segment in ordered:
        payload = segment_payload(segment, labeler)
        if (translation := translations.get(segment.segment_id)) is not None:
            payload["translation"] = {"language": translation.language, "text": translation.text}
        payloads.append(payload)
    return {"source": source, "segments": payloads}


@router.get("/sessions/{session_id}/minutes", response_model=Minutes)
def minutes(session_id: str, c: Container) -> dict[str, str]:
    c.store.read_meta(session_id)
    markdown = c.store.read_minutes(session_id)
    if markdown is None:
        raise ApiError(404, "minutes_not_found", id=session_id)
    return {"markdown": markdown}


@router.post("/sessions/{session_id}/minutes", status_code=status.HTTP_202_ACCEPTED)
def regenerate_minutes(
    session_id: str, c: Container, body: RegenerateMinutes | None = None
) -> None:
    c.store.read_meta(session_id)
    template = body.template if body is not None else None
    check_template(c, template)
    current = c.manager.current
    if current is not None and current.status is not None and current.id == session_id:
        raise ApiError(409, "session_still_recording", id=session_id)
    c.regenerate_minutes(session_id, template)


def _summary(c: ApiContainer, session_id: str) -> dict[str, Any]:
    current = c.manager.current
    if current is not None and current.status is not None and current.id == session_id:
        return c.manager.summary(current)
    return session_summary(c.store, session_id)
