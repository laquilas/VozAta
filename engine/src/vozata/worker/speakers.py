"""Speaker identification on the worker (phase 45): diarization jobs and the live embedder."""

from __future__ import annotations

import logging
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from vozata.domain import SpeakerTurn
from vozata.ports import Cancellable, Diarizer, SpeakerEmbedder

_log = logging.getLogger(__name__)
KEEP_FINISHED = 20  # finished jobs kept for their status (the engine polls, then forgets)


@dataclass
class DiarizeJob:
    id: str
    state: str = "running"  # running | done | failed | cancelled
    turns: list[SpeakerTurn] = field(default_factory=list)
    message: str | None = None
    diarizer: Diarizer | None = None


class DiarizeJobs:
    """One diarization at a time, each in its own thread: the upload is written to a temporary
    WAV, the job is polled, and `cancel` stops the diarizer (its child process)."""

    def __init__(
        self,
        factory: Callable[[], Diarizer],
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    ) -> None:
        self._factory = factory
        self._new_id = new_id
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._jobs: dict[str, DiarizeJob] = {}

    def start(self, wav: bytes, min_speakers: int | None, max_speakers: int | None) -> str:
        job = DiarizeJob(self._new_id())
        with self._lock:
            self._jobs[job.id] = job
            self._forget_old()
        thread = threading.Thread(
            target=self._run,
            args=(job, wav, min_speakers, max_speakers),
            name="diarize",
            daemon=True,
        )
        thread.start()
        return job.id

    def status(self, job_id: str) -> DiarizeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.state == "running":
            job.state = "cancelled"
            if isinstance(job.diarizer, Cancellable):
                job.diarizer.cancel()
        return True

    def _run(self, job: DiarizeJob, wav: bytes, low: int | None, high: int | None) -> None:
        with self._run_lock, tempfile.TemporaryDirectory(prefix="vozata-worker-") as folder:
            if job.state == "cancelled":
                return
            path = Path(folder) / "system.wav"
            path.write_bytes(wav)
            try:
                job.diarizer = self._factory()
                if job.state == "cancelled":
                    return
                turns = job.diarizer.diarize(path, low, high)
                if job.state != "cancelled":
                    job.turns, job.state = turns, "done"
            except Exception as error:
                if job.state != "cancelled":
                    _log.warning("Diarization job %s failed: %s", job.id, error)
                    job.state, job.message = "failed", str(error) or type(error).__name__
            finally:
                if job.diarizer is not None:
                    job.diarizer.close()

    def _forget_old(self) -> None:
        finished = [job_id for job_id, job in self._jobs.items() if job.state != "running"]
        for job_id in finished[: max(0, len(finished) - KEEP_FINISHED)]:
            del self._jobs[job_id]


class EmbedService:
    """The live speaker embedder, loaded on the first request and kept; one request at a time."""

    def __init__(self, factory: Callable[[], SpeakerEmbedder]) -> None:
        self._factory = factory
        self._embedder: SpeakerEmbedder | None = None
        self._lock = threading.Lock()

    def embed(self, samples: np.ndarray) -> np.ndarray:
        with self._lock:
            if self._embedder is None:
                self._embedder = self._factory()
            return self._embedder.embed(samples)

    def close(self) -> None:
        with self._lock:
            if self._embedder is not None:
                self._embedder.close()
                self._embedder = None
