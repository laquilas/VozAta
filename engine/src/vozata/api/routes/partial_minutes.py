"""Minutes of part of a meeting (phase 48): so far while recording, or a time range."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.partial_minutes_job import PartialRequest
from vozata.api.routes.templates import check_template
from vozata.api.schemas import (
    PartialMinutesDetail,
    PartialMinutesList,
    PartialMinutesRequest,
    PartialMinutesStarted,
    PartialMinutesSummary,
)
from vozata.minutes.partial_minutes import delete_partial_minutes

router = APIRouter(tags=["partial minutes"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post(
    "/sessions/{session_id}/partial-minutes",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PartialMinutesStarted,
)
def start(
    session_id: str, c: Container, body: PartialMinutesRequest | None = None
) -> PartialMinutesStarted:
    """While the meeting is recorded: what was said so far (`start` / `end` optional). Otherwise:
    the range `[start, end)` (`start` default 0, `end` default the end of the transcript).
    Then `partial_minutes_ready` or an `error` event."""
    meta = c.store.read_meta(session_id)
    body = body or PartialMinutesRequest()
    check_template(c, body.template)
    if c.partial_minutes is None:
        raise ApiError(503, "partial_minutes_unavailable")
    current = c.manager.current
    live = current is not None and current.status is not None and current.id == session_id
    if live and meta.get("live_transcription") is False:  # audio only: nothing transcribed yet
        raise ApiError(409, "live_transcription_off", id=session_id)
    start_at = body.start or 0.0
    if body.end is not None and body.end <= start_at:
        raise ApiError(422, "invalid_range")
    request = PartialRequest(
        session_id, start_at, body.end, "button" if live else "range", live, body.template
    )
    partial_id = c.partial_minutes.start(request)
    if partial_id is None:
        raise ApiError(409, "partial_minutes_in_progress")
    return PartialMinutesStarted(partial_id=partial_id)


@router.get("/sessions/{session_id}/partial-minutes", response_model=PartialMinutesList)
def list_partial(session_id: str, c: Container) -> PartialMinutesList:
    """Oldest first, without the Markdown."""
    c.store.read_meta(session_id)
    items = c.store.read_partial_minutes(session_id)
    return PartialMinutesList(
        items=[PartialMinutesSummary(**_fields(item.to_dict())) for item in items]
    )


@router.get(
    "/sessions/{session_id}/partial-minutes/{partial_id}", response_model=PartialMinutesDetail
)
def read_partial(session_id: str, partial_id: str, c: Container) -> PartialMinutesDetail:
    c.store.read_meta(session_id)
    for item in c.store.read_partial_minutes(session_id):
        if item.id == partial_id:
            return PartialMinutesDetail(**item.to_dict())
    raise ApiError(404, "partial_minutes_not_found", id=partial_id)


@router.delete(
    "/sessions/{session_id}/partial-minutes/{partial_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_partial(session_id: str, partial_id: str, c: Container) -> Response:
    c.store.read_meta(session_id)
    if not delete_partial_minutes(c.store, session_id, partial_id):
        raise ApiError(404, "partial_minutes_not_found", id=partial_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _fields(data: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in data.items() if key != "markdown"}
