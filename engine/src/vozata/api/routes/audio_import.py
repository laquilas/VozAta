"""An audio file recorded elsewhere as a meeting (phase 60): `POST /sessions/import-audio`."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import AudioImported
from vozata.api.uploads import save_body
from vozata.ports import AudioDecodeError
from vozata.storage.audio_import import AudioFileImporter

MAX_AUDIO_IMPORT_BYTES = 4 << 30  # a few hours of uncompressed WAV; far more as mp3 / m4a
MEDIA_TYPE = "application/octet-stream"

router = APIRouter(tags=["sessions"])
Container = Annotated[ApiContainer, Depends(container)]


@router.post(
    "/sessions/import-audio",
    status_code=202,
    response_model=AudioImported,
    openapi_extra={"requestBody": {"content": {MEDIA_TYPE: {}}, "required": True}},
)
async def import_audio(
    request: Request,
    c: Container,
    name: Annotated[str, Query(min_length=1, max_length=260)],
    recorded_at: datetime | None = None,
) -> dict[str, str]:
    """Read an audio or video file (raw body; `name` is its file name, `recorded_at` its time)
    as a new meeting named after the file, and queue its processing as after Stop: `processing`
    and `status` events follow. `422 audio_invalid` / `audio_empty`, `413 audio_too_large`; no
    meeting is added then."""
    importer = c.audio_importer
    if importer is None:
        raise ApiError(503, "import_unavailable")
    limit = MAX_AUDIO_IMPORT_BYTES
    work = Path(tempfile.mkdtemp(prefix="vozata-audio-"))
    try:
        upload = work / f"upload{Path(name).suffix[:16]}"
        await save_body(
            request, upload, limit, lambda: ApiError(413, "audio_too_large", max_gb=limit >> 30)
        )
        session_id = await run_in_threadpool(_import, importer, upload, name, recorded_at)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    c.manager.process_imported(session_id)
    return {"id": session_id}


def _import(
    importer: AudioFileImporter, upload: Path, name: str, recorded_at: datetime | None
) -> str:
    local = recorded_at.astimezone() if recorded_at else None  # naive: already local time
    try:
        return importer.import_file(upload, name, local)
    except AudioDecodeError as error:
        if str(error) == "audio_empty":
            raise ApiError(422, "audio_empty") from None
        raise ApiError(422, "audio_invalid", reason=error) from None
