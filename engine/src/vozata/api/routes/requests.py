"""`GET /sessions/{id}/requests` (phase 59): the meeting's request history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import RequestEntryOut, RequestList

router = APIRouter(tags=["requests"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get("/sessions/{session_id}/requests", response_model=RequestList)
def list_requests(session_id: str, c: Container) -> RequestList:
    """Oldest first; `404 session_not_found`."""
    c.store.read_meta(session_id)
    items = c.store.read_requests(session_id)
    return RequestList(items=[RequestEntryOut(**item.to_dict()) for item in items])
