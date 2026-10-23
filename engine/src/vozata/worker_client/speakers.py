"""Speaker identification on the VozAta worker, with a switch to this PC (phase 45)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from vozata.domain import SpeakerTurn
from vozata.ports import (
    Cancellable,
    DiarizationError,
    Diarizer,
    FallbackNotices,
    SpeakerEmbedder,
    WorkerUnreachableError,
)
from vozata.worker_client.client import WorkerClient, WorkerRequestError

POLL_SECONDS = 1.0


class WorkerDiarizer:
    """`Diarizer` and `Cancellable`: uploads `system.wav`, polls the job and, on `cancel()`,
    cancels it on the worker (the queue's step can be pre-empted by a recording as before). A
    worker that does not answer, at the start or during the job, is replaced by the local
    diarizer, once, with a notice."""

    def __init__(
        self,
        client: WorkerClient,
        local_factory: Callable[[], Diarizer],
        notices: FallbackNotices,
        poll: float = POLL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._local_factory = local_factory
        self._notices = notices
        self._poll = poll
        self._sleep = sleep
        self._local: Diarizer | None = None
        self._job: str | None = None
        self._cancelled = threading.Event()

    def diarize(
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        if self._cancelled.is_set():
            raise DiarizationError("cancelled")
        if self._local is None:
            try:
                return self._remote(wav, min_speakers, max_speakers)
            except WorkerUnreachableError as error:
                if self._cancelled.is_set():
                    raise DiarizationError("cancelled") from error
                self._notices.fallback("speakers", error.host)
                self._local = self._local_factory()
        return self._local.diarize(wav, min_speakers, max_speakers)

    def cancel(self) -> None:
        self._cancelled.set()
        if self._job is not None:
            self._client.diarize_cancel(self._job)
        if isinstance(self._local, Cancellable):
            self._local.cancel()

    def close(self) -> None:
        self._client.close()
        if self._local is not None:
            self._local.close()

    def _remote(self, wav: Path, low: int | None, high: int | None) -> list[SpeakerTurn]:
        try:
            self._job = self._client.diarize_start(wav, low, high)
            while True:
                if self._cancelled.is_set():
                    self._client.diarize_cancel(self._job)
                    raise DiarizationError("cancelled")
                status = self._client.diarize_status(self._job)
                state = status.get("state")
                if state == "done":
                    return [
                        SpeakerTurn(float(t["start"]), float(t["end"]), int(t["speaker_index"]))
                        for t in status.get("turns", [])
                    ]
                if state in ("failed", "cancelled"):
                    raise DiarizationError(str(status.get("message") or state))
                self._sleep(self._poll)
        except WorkerRequestError as error:
            raise DiarizationError(str(error)) from error


class WorkerEmbedder:
    """`SpeakerEmbedder` of the live speaker labels: one request per clip; a lost worker is
    replaced by the local embedder, once, with a notice."""

    def __init__(
        self,
        client: WorkerClient,
        local_factory: Callable[[], SpeakerEmbedder],
        notices: FallbackNotices,
    ) -> None:
        self._client = client
        self._local_factory = local_factory
        self._notices = notices
        self._local: SpeakerEmbedder | None = None

    def embed(self, samples: np.ndarray) -> np.ndarray:
        if self._local is None:
            try:
                return self._client.embed(samples)
            except WorkerUnreachableError as error:
                self._notices.fallback("speakers", error.host)
                self._local = self._local_factory()
        return self._local.embed(samples)

    def close(self) -> None:
        self._client.close()
        if self._local is not None:
            self._local.close()
