"""`GET /sessions/{id}/export?format=md|docx|pdf`: minutes and transcript as a download (11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.payloads import session_summary
from vozata.export.document import build_document

router = APIRouter(tags=["sessions"])


@router.get(
    "/sessions/{session_id}/export",
    response_class=Response,
    responses={200: {"description": "The file, named `<id>-minutes.<ext>`"}},
)
def export_session(
    session_id: str,
    c: Annotated[ApiContainer, Depends(container)],
    export_format: Annotated[str, Query(alias="format")] = "md",
) -> Response:
    exporter = c.exporters.get(export_format)
    if exporter is None:
        raise ApiError(
            400, "unsupported_format", format=export_format, allowed=", ".join(sorted(c.exporters))
        )
    summary = session_summary(c.store, session_id)
    minutes_path = c.store.paths(session_id).minutes_md
    minutes = minutes_path.read_text(encoding="utf-8") if minutes_path.is_file() else None
    _, segments = c.store.load_transcript_with_source(session_id)
    document = build_document(summary, minutes, segments, c.labeler, c.localizer)
    filename = f"{session_id}-minutes.{exporter.extension}"
    return Response(
        content=exporter.export(document),
        media_type=exporter.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
