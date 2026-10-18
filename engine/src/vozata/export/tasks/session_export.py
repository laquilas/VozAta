"""Export a session's selected action items through a `TaskExporter` (phase 23).

Each item is created on its own, so one failure never blocks the others; a created item gets
its `exported_url` saved at once and is never exported again.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import ActionItem, TaskDraft
from vozata.formatting import format_timestamp
from vozata.ports import Localizer, SessionRepository, TaskExporter, TaskExportError


@dataclass
class ExportResult:
    created: list[dict[str, str]] = field(default_factory=list)  # {item_id, url}
    failed: list[dict[str, str]] = field(default_factory=list)  # {item_id, error} (localized)


def export_action_items(
    store: SessionRepository,
    session_id: str,
    exporter: TaskExporter,
    item_ids: Sequence[str],
    localizer: Localizer,
) -> ExportResult:
    """Create one task per selected item; raises `SessionNotFoundError`."""
    t = localizer.t
    meta = store.read_meta(session_id)
    folder = store.folder(session_id)
    starts = {segment.segment_id: segment.start for segment in store.load_transcript(session_id)}
    result = ExportResult()
    with store.action_items_lock():
        items = {item.id: item for item in store.read_action_items(session_id)}
        for item_id in dict.fromkeys(item_ids):
            item = items.get(item_id)
            if item is None:
                result.failed.append(_failure(item_id, t("errors.tasks.unknown_item", id=item_id)))
                continue
            if item.exported_url:
                message = t("errors.tasks.already_exported", url=item.exported_url)
                result.failed.append(_failure(item_id, message))
                continue
            draft = _draft(item, meta, session_id, folder, starts, localizer)
            try:
                url = exporter.create(draft)
            except TaskExportError as error:
                message = t(f"errors.tasks.{error.code}", target=exporter.name, **error.params)
                result.failed.append(_failure(item_id, message))
                continue
            items[item_id] = dataclasses.replace(item, exported_url=url)
            store.write_action_items(session_id, list(items.values()))
            result.created.append({"item_id": item_id, "url": url})
    return result


def _failure(item_id: str, message: str) -> dict[str, str]:
    return {"item_id": item_id, "error": message}


def _draft(
    item: ActionItem,
    meta: dict[str, Any],
    session_id: str,
    folder: Path | None,
    starts: dict[str, float],
    localizer: Localizer,
) -> TaskDraft:
    t = localizer.t
    lines = [t("tasks.source", title=_title(meta, session_id, localizer), session_id=session_id)]
    times = [starts[i] for i in item.source_segment_ids if i in starts]
    if times:
        lines.append(t("tasks.time", time=format_timestamp(min(times))))
    if item.owner:
        lines.append(t("tasks.owner", owner=item.owner))
    if item.due:
        lines.append(t("tasks.due", due=item.due))
    if folder is not None:  # file backend
        lines.append(t("tasks.folder", folder=str(folder.resolve())))
    return TaskDraft(item.description, "\n".join(lines), item.due)


def _title(meta: dict[str, Any], session_id: str, localizer: Localizer) -> str:
    """`Meeting of 2026-10-15 20:23`, as in exported documents (phase 11)."""
    started = meta.get("started_at")
    try:
        date = datetime.fromisoformat(str(started)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        date = session_id
    return localizer.t("export.title", date=date)
