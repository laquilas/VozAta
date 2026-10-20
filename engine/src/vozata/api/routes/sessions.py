"""Session routes tagged 06: lifecycle of the current session, history, transcript, minutes."""

from __future__ import annotations

from datetime import date
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
    SessionDays,
    SessionDetail,
    SessionList,
    SessionSummary,
    StartSession,
    Transcript,
    UpdateSession,
)
from vozata.api.session_days import EPOCH, group_by_day, local_bounds
from vozata.api.session_manager import StartOptions
from vozata.domain import AudioTrack, ConversationLanguage, TranslationTarget
from vozata.session_title import TitleTooLongError, normalize_title

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=SessionSummary)
def start_session(body: StartSession, c: Container) -> dict[str, Any]:
    check_template(c, body.template)
    title = _title(body.title)
    options = StartOptions(
        language=ConversationLanguage(body.language) if body.language else None,
        mic_device=body.mic_device_id,
        system_device=body.system_device_id,
        template=body.template,
        vocabulary=tuple(body.vocabulary or ()),
        translate_to=TranslationTarget(body.translate_to) if body.translate_to else None,
        title=title,
        live_transcription=body.live_transcription,
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


@router.get("/sessions", response_model=SessionList | SessionDays)
def list_sessions(
    c: Container,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    first: Annotated[date | None, Query(alias="from")] = None,
    last: Annotated[date | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    """The paged list, or with `from` and `to` (local dates, both included) the meetings of
    those days grouped by local start day (phase 36)."""
    if first is not None or last is not None:
        return _days(c, first, last)
    ids = c.store.list_sessions()
    return {
        "items": [_summary(c, session_id) for session_id in ids[offset : offset + limit]],
        "total": len(ids),
    }


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def session_detail(session_id: str, c: Container) -> dict[str, Any]:
    meta = c.store.read_meta(session_id)
    detail = {**meta, **_summary(c, session_id), "storage": c.storage.backend}
    folder = c.store.folder(session_id)
    if folder is not None:  # file backend
        detail["files"] = c.store.files(session_id)
        detail["folder"] = str(folder.resolve())
    detail["audio"] = _audio(c, session_id)
    return detail


def _audio(c: ApiContainer, session_id: str) -> dict[str, float]:
    """The duration in seconds of every playable track (phase 32)."""
    durations = {}
    for track in AudioTrack if c.audio is not None else ():
        pcm = c.audio.track(session_id, track)
        if pcm is not None:
            durations[track.value] = round(pcm.frames / pcm.rate, 3)
    return durations


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def update_session(session_id: str, body: UpdateSession, c: Container) -> dict[str, Any]:
    """Rename a meeting (phase 35), also while it is being recorded."""
    return c.manager.rename(session_id, _title(body.title))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, c: Container) -> None:
    """Delete a meeting (phase 36): permanently in the database, to the Recycle Bin for the file
    backend; its search hits go with it."""
    try:
        c.manager.delete(session_id)
    except OSError as error:  # e.g. a file of the session is open in another program
        raise ApiError(500, "session_delete_failed", id=session_id, reason=error) from None
    if c.audio is not None:
        c.audio.delete(session_id)  # sqlite: cached WAVs, space reclaimed in the background (32)
    if c.search_index is not None:
        c.search_index.index_session(session_id, [])


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
    if not c.regenerate_minutes(session_id, template):  # phase 40: a queue job
        raise ApiError(409, "session_still_active", id=session_id)


def _title(raw: str | None) -> str | None:
    """The normalized title (phase 35); `422 title_too_long` past the limit."""
    try:
        return normalize_title(raw)
    except TitleTooLongError as error:
        raise ApiError(422, "title_too_long", max=error.max_length) from None


def _days(c: ApiContainer, first: date | None, last: date | None) -> dict[str, Any]:
    if first is None or last is None or first > last:
        raise ApiError(422, "invalid_date_range")
    start, end = local_bounds(first, last)
    summaries = [_summary(c, session_id) for session_id in c.store.list_range(start, end)]
    return {
        **group_by_day(summaries),
        "has_earlier": bool(c.store.list_range(EPOCH, start)),
        "storage": c.storage.backend,
    }


def _summary(c: ApiContainer, session_id: str) -> dict[str, Any]:
    current = c.manager.current
    if current is not None and current.status is not None and current.id == session_id:
        return c.manager.summary(current)
    return session_summary(c.store, session_id, processing=c.manager.processing(session_id))
