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
    """Repair an `interrupted` session and run its stop steps in the background.

    Progress: `status` events (`finalizing` → `done`) with the session id; a failed repair sends
    `error` `recovery_failed` and the session stays `interrupted`. `409 session_not_interrupted`,
    `409 session_already_active` (a recording or another recovery is running),
    `404 session_not_found`.
    """
    c.manager.recover(session_id)
