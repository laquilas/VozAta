"""The worker's speaker routes (phase 45): `/diarize` jobs and `/embed`."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from vozata.worker.speakers import DiarizeJobs, EmbedService

UNAVAILABLE = "worker_speakers_unavailable"
FLOAT32_BYTES = 4


def add_speaker_routes(
    router: APIRouter, jobs: DiarizeJobs | None, embedder: EmbedService | None
) -> None:
    """Without `jobs` / `embedder` (no `HF_TOKEN` on the worker) the routes answer 503."""

    @router.post("/diarize", status_code=202)
    async def diarize(
        request: Request, min_speakers: int | None = None, max_speakers: int | None = None
    ) -> JSONResponse:
        """Body: the meeting's `system.wav`. Then poll `GET /diarize/{job_id}`."""
        if jobs is None:
            return _error(503, UNAVAILABLE)
        wav = await request.body()
        if not wav:
            return _error(422, "worker_invalid_audio")
        job_id = jobs.start(wav, min_speakers, max_speakers)
        return JSONResponse({"job_id": job_id}, status_code=202)

    @router.get("/diarize/{job_id}")
    def diarize_status(job_id: str) -> JSONResponse:
        job = jobs.status(job_id) if jobs is not None else None
        if job is None:
            return _error(404, "worker_job_not_found")
        turns = [
            {"start": turn.start, "end": turn.end, "speaker_index": turn.speaker_index}
            for turn in job.turns
        ]
        return JSONResponse({"state": job.state, "turns": turns, "message": job.message})

    @router.delete("/diarize/{job_id}", status_code=204)
    def diarize_cancel(job_id: str) -> Response:
        if jobs is None or not jobs.cancel(job_id):
            return _error(404, "worker_job_not_found")
        return Response(status_code=204)

    @router.post("/embed")
    async def embed(request: Request) -> JSONResponse:
        """Body: float32 little-endian mono samples; reply `{vector}`."""
        if embedder is None:
            return _error(503, UNAVAILABLE)
        body = await request.body()
        if not body or len(body) % FLOAT32_BYTES:
            return _error(422, "worker_invalid_audio")
        samples = np.frombuffer(body, dtype="<f4").astype(np.float32)
        vector = await run_in_threadpool(embedder.embed, samples)
        return JSONResponse({"vector": [float(value) for value in np.asarray(vector).ravel()]})


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)
