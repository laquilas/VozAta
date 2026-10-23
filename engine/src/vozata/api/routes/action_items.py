"""Action items (phase 23): extract, list, edit and export them as work items or issues."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.request_log import record, refused
from vozata.api.schemas import ActionItems, EditActionItems, ExportActionItems, ExportedActionItems
from vozata.domain import ActionItem, optional_text
from vozata.export.tasks.session_export import export_action_items

router = APIRouter(tags=["action-items"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post("/sessions/{session_id}/action-items", status_code=status.HTTP_202_ACCEPTED)
def extract(session_id: str, c: Container) -> None:
    """Extract again in the processing queue; the result comes as `action_items_ready`.
    `409 session_still_active` while the meeting is already queued or processed."""
    c.store.read_meta(session_id)  # 404 session_not_found
    _check_finished(c, session_id)
    if c.extract_action_items is None:
        raise ApiError(503, "action_items_unavailable")
    request_id = record(c.requests, session_id, "action_items", "app")  # phase 59
    if not c.extract_action_items(session_id):  # phase 40: a queue job
        refused(c.requests, session_id, request_id, "session_still_active")
        raise ApiError(409, "session_still_active", id=session_id)


@router.get("/sessions/{session_id}/action-items", response_model=ActionItems)
def list_items(session_id: str, c: Container) -> dict[str, Any]:
    c.store.read_meta(session_id)
    return _view(c, c.store.read_action_items(session_id))


@router.put("/sessions/{session_id}/action-items", response_model=ActionItems)
def edit_items(session_id: str, body: EditActionItems, c: Container) -> dict[str, Any]:
    """Save edited description / owner / due; exported items stay as they were exported."""
    c.store.read_meta(session_id)
    with c.store.action_items_lock():
        items = {item.id: item for item in c.store.read_action_items(session_id)}
        for edit in body.items:
            item = items.get(edit.id)
            if item is None:
                raise ApiError(422, "unknown_action_item", id=edit.id)
            description = optional_text(edit.description)
            if description is None:
                raise ApiError(422, "empty_action_item", id=edit.id)
            if item.exported_url:
                continue
            items[edit.id] = dataclasses.replace(
                item,
                description=description,
                owner=optional_text(edit.owner),
                due=optional_text(edit.due),
            )
        saved = list(items.values())
        c.store.write_action_items(session_id, saved)
    return _view(c, saved)


@router.post("/sessions/{session_id}/action-items/export", response_model=ExportedActionItems)
def export(session_id: str, body: ExportActionItems, c: Container) -> dict[str, Any]:
    """One work item / issue per selected item; already exported items are refused."""
    c.store.read_meta(session_id)
    exporter = c.task_exporter(body.target)
    if exporter is None:
        allowed = ", ".join(c.task_targets()) or "—"
        raise ApiError(422, "unknown_task_target", target=body.target, allowed=allowed)
    try:
        result = export_action_items(c.store, session_id, exporter, body.item_ids, c.localizer)
    finally:
        close = getattr(exporter, "close", None)
        if close is not None:
            close()
    return {"created": result.created, "failed": result.failed}


def _view(c: ApiContainer, items: list[ActionItem]) -> dict[str, Any]:
    return {"items": [item.to_dict() for item in items], "targets": c.task_targets()}


def _check_finished(c: ApiContainer, session_id: str) -> None:
    current = c.manager.current
    if current is not None and current.status is not None and current.id == session_id:
        raise ApiError(409, "action_items_still_recording", id=session_id)
