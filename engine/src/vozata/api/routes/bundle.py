"""A meeting as a ZIP of its session folder (phase 39): `GET /sessions/{id}/bundle` and
`POST /sessions/import`."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import BundleImported
from vozata.api.uploads import save_body
from vozata.domain import ImportedSession
from vozata.export.bundle import MEDIA_TYPE, zip_folder
from vozata.ports import BundleImporter
from vozata.storage import bundle_import
from vozata.storage.bundle_import import (
    BundleError,
    BundleTooLargeError,
    SessionExistsError,
    extract_bundle,
)
from vozata.storage.folder_writer import write_folder
from vozata.storage.migration import NotEnoughSpaceError

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


@router.post(
    "/sessions/import",
    response_model=BundleImported,
    openapi_extra={"requestBody": {"content": {MEDIA_TYPE: {}}, "required": True}},
)
async def import_bundle(request: Request, c: Container) -> dict[str, str]:
    """Read a ZIP of `GET /sessions/{id}/bundle` (raw body): a new meeting (`imported`), or the
    audio of a kept meeting that has none (`audio_restored`). `409 session_exists` when the
    meeting is there with its audio, `422 bundle_invalid`, `413 bundle_too_large`, `507
    not_enough_space`; nothing is changed then."""
    importer = c.bundle_importer
    if importer is None:
        raise ApiError(503, "import_unavailable")
    limit = bundle_import.MAX_BUNDLE_BYTES
    work = Path(tempfile.mkdtemp(prefix="vozata-import-"))
    try:
        archive = work / "bundle.zip"
        await save_body(request, archive, limit, lambda: _too_large(limit))
        result = await run_in_threadpool(_import, c, importer, archive, work / "unpacked", limit)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"id": result.id, "mode": result.mode}


def _import(
    c: ApiContainer, importer: BundleImporter, archive: Path, destination: Path, limit: int
) -> ImportedSession:
    try:
        result = importer.import_folder(extract_bundle(archive, destination, limit))
    except BundleTooLargeError:
        raise _too_large(limit) from None
    except BundleError as error:
        raise ApiError(422, "bundle_invalid", reason=error) from None
    except SessionExistsError as error:
        raise ApiError(409, "session_exists", id=str(error)) from None
    except NotEnoughSpaceError as error:
        raise ApiError(
            507, "not_enough_space", needed_mb=error.needed >> 20, free_mb=error.free >> 20
        ) from None
    if c.search_index is not None:  # the file backend's index; SQLite indexes on insert
        c.search_index.index_session(result.id, c.store.load_transcript(result.id))
    return result


def _too_large(limit: int) -> ApiError:
    return ApiError(413, "bundle_too_large", max_gb=limit >> 30)
