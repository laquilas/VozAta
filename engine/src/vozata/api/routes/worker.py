"""`GET /worker/discover` and `POST /worker/pair`: find and pair a VozAta worker (phase 47)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.errors import ApiError
from vozata.api.schemas import FoundWorkerOut, PairedWorkerOut, PairWorkerRequest, WorkersFound
from vozata.ports import WorkerUnreachableError
from vozata.settings_file import SettingsWriteError
from vozata.worker_client.pairing import PairingRefusedError

router = APIRouter(tags=["worker"])


@router.get("/worker/discover", response_model=WorkersFound)
async def discover(c: Annotated[ApiContainer, Depends(container)]) -> WorkersFound:
    """The workers that answered a broadcast on this PC's networks (about 1.5 s)."""
    found = await run_in_threadpool(c.discover_workers, c.settings_file.current)
    return WorkersFound(
        workers=[
            FoundWorkerOut(id=w.id, name=w.name, url=w.url, version=w.version, gpu=w.gpu)
            for w in found
        ]
    )


@router.post("/worker/pair", response_model=PairedWorkerOut)
async def pair(
    body: PairWorkerRequest, c: Annotated[ApiContainer, Depends(container)]
) -> PairedWorkerOut:
    """Trade the code shown on the worker PC for its token, then save `WORKER_URL`,
    `WORKER_TOKEN` and `WORKER_ID` (they apply from the next recording)."""
    try:
        paired = await run_in_threadpool(c.pair_worker, body.url, body.code)
    except PairingRefusedError as error:
        raise ApiError(409, error.code) from error
    except WorkerUnreachableError as error:
        raise ApiError(502, "worker_unreachable", host=error.host) from error
    values = {"WORKER_URL": body.url, "WORKER_TOKEN": paired.token, "WORKER_ID": paired.id or ""}
    try:
        c.settings_file.update(values)
    except SettingsWriteError as error:
        raise ApiError(503, "settings_write_failed", reason=error) from error
    return PairedWorkerOut(id=paired.id, name=paired.name, url=body.url)
