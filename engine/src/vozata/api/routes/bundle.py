"""A meeting as a ZIP of its session folder (phase 39): `GET /sessions/{id}/bundle`."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.export.bundle import MEDIA_TYPE, zip_folder
from vozata.storage.folder_writer import write_folder

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.get(
    "/sessions/{session_id}/bundle",
    response_class=FileResponse,
    responses={200: {"content": {MEDIA_TYPE: {}}, "description": "The ZIP, named `<id>.zip`."}},
)
def session_bundle(session_id: str, c: Container) -> FileResponse:
    """The session folder (metadata, transcripts, speakers, minutes, action items, `mic.wav`,
    `system.wav`) zipped; `POST /sessions/import` reads it back. `409 session_still_active` for
    the live session. Built in a temporary folder that is removed once the file is sent."""
    c.store.read_meta(session_id)  # SessionNotFoundError: 404 session_not_found
    c.manager.check_finished(session_id)
    work = Path(tempfile.mkdtemp(prefix="vozata-bundle-"))
    try:
        folder = write_folder(c.store, c.audio, session_id, work, c.labeler)
        archive = work / f"{session_id}.zip"
        zip_folder(folder, archive)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type=MEDIA_TYPE,
        filename=archive.name,
        background=BackgroundTask(shutil.rmtree, work, ignore_errors=True),
    )
