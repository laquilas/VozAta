"""Folder import route (phase 33): progress and errors of the import of old session folders."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import Migration

router = APIRouter(tags=["storage"])
Container = Annotated[ApiContainer, Depends(container)]

_DISABLED: dict[str, Any] = {
    "state": "disabled",
    "done": 0,
    "total": 0,
    "current": None,
    "paused": False,
    "imported": 0,
    "skipped": 0,
    "needed_bytes": None,
    "free_bytes": None,
    "message": None,
    "errors": [],
}


@router.get("/migration", response_model=Migration)
def migration(c: Container) -> dict[str, Any]:
    """The import of the folders recorded before phase 31 into `vozata.db`.

    `disabled` with the file backend. Live progress: `migration_progress` and `migration_done`
    events.
    """
    return _DISABLED if c.migration is None else c.migration.summary()
