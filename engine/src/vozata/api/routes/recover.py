"""Crash recovery route (phase 17): finish a session a crash cut short."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post("/sessions/{session_id}/recover", status_code=status.HTTP_202_ACCEPTED)
def recover_session(session_id: str, c: Container) -> None:
    """Queue an `interrupted` session's recovery job (repair, then the stop steps).

    It never blocks a recording. Progress: `processing` events and `status` (`finalizing` →
    `done`) with the session id; a failed repair sends `error` `recovery_failed`, the job ends
    `failed` and the session stays `interrupted`. `409 session_not_interrupted`,
    `404 session_not_found`.
    """
    c.manager.recover(session_id)
