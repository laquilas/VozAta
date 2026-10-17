"""`POST /ask` (phase 24): a question about one session or all of them, answered via events."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import AskAccepted, AskQuestion

router = APIRouter(tags=["ask"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post("/ask", status_code=status.HTTP_202_ACCEPTED, response_model=AskAccepted)
def ask(body: AskQuestion, c: Container) -> dict[str, str]:
    """The answer streams as `answer_chunk` events and ends with `answer_done`."""
    if body.session_id is not None:
        c.store.read_meta(body.session_id)  # 404 session_not_found
    if c.ask is None:
        raise ApiError(503, "ask_unavailable")
    answer_id = uuid.uuid4().hex
    if not c.ask.start(answer_id, body.question.strip(), body.session_id):
        raise ApiError(409, "answer_in_progress")
    return {"answer_id": answer_id}
