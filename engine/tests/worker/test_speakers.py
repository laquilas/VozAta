"""Speaker identification on the worker (phase 45): jobs, the embedder and the routes."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from vozata.api.system_info import GpuInfo
from vozata.domain import SpeakerTurn
from vozata.ports import DiarizationError
from vozata.worker.app import create_worker_app
from vozata.worker.speakers import DiarizeJobs, EmbedService
from vozata.worker.speech import LoadedModel, SpeechService

TOKEN = "t0k"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TURNS = [SpeakerTurn(0.0, 2.5, 0), SpeakerTurn(2.5, 4.0, 1)]


class _Diarizer:
    def __init__(
        self, turns=TURNS, gate: threading.Event | None = None, error: Exception | None = None
    ):  # type: ignore[no-untyped-def]
        self.turns, self.gate, self.error = turns, gate, error
        self.seen: list[tuple[bytes, int | None, int | None]] = []
        self.cancelled = threading.Event()
        self.closed = False

    def diarize(self, wav: Path, low: int | None, high: int | None) -> list[SpeakerTurn]:
        self.seen.append((wav.read_bytes(), low, high))
        if self.gate is not None:
            self.gate.wait(5)
        if self.cancelled.is_set():
            raise DiarizationError("cancelled")
        if self.error is not None:
            raise self.error
        return self.turns

    def cancel(self) -> None:
        self.cancelled.set()
        if self.gate is not None:
            self.gate.set()

    def close(self) -> None:
        self.closed = True


def _wait(jobs: DiarizeJobs, job_id: str) -> str:
    for _ in range(500):
        job = jobs.status(job_id)
        if job is not None and job.state != "running":
            return job.state
        time.sleep(0.01)
    raise AssertionError("the job did not finish")


def test_a_job_diarizes_the_upload_and_keeps_its_turns() -> None:
    diarizer = _Diarizer()
    jobs = DiarizeJobs(lambda: diarizer, new_id=lambda: "j1")

    job_id = jobs.start(b"RIFF....", 2, 5)

    assert (job_id, _wait(jobs, job_id)) == ("j1", "done")
    assert jobs.status("j1").turns == TURNS  # type: ignore[union-attr]
    assert diarizer.seen == [(b"RIFF....", 2, 5)]
    assert diarizer.closed


def test_a_failing_job_says_why() -> None:
    jobs = DiarizeJobs(lambda: _Diarizer(error=DiarizationError("no GPU memory")))

    job_id = jobs.start(b"x", None, None)

    assert _wait(jobs, job_id) == "failed"
    assert jobs.status(job_id).message == "no GPU memory"  # type: ignore[union-attr]


def test_cancel_stops_the_running_diarizer() -> None:
    gate = threading.Event()
    diarizer = _Diarizer(gate=gate)
    jobs = DiarizeJobs(lambda: diarizer)
    job_id = jobs.start(b"x", None, None)
    for _ in range(500):
        if diarizer.seen:
            break
        time.sleep(0.01)

    assert jobs.cancel(job_id)
    assert _wait(jobs, job_id) == "cancelled"
    assert diarizer.cancelled.is_set()
    assert not jobs.cancel("unknown")


def test_old_finished_jobs_are_forgotten() -> None:
    ids = iter(str(i) for i in range(100))
    jobs = DiarizeJobs(lambda: _Diarizer(), new_id=lambda: next(ids))
    first = jobs.start(b"x", None, None)
    _wait(jobs, first)
    for _ in range(25):
        _wait(jobs, jobs.start(b"x", None, None))

    jobs.start(b"x", None, None)

    assert jobs.status(first) is None


class _Embedder:
    def __init__(self) -> None:
        self.closed = False

    def embed(self, samples: np.ndarray) -> np.ndarray:
        return np.array([len(samples), 1.5], dtype=np.float32)

    def close(self) -> None:
        self.closed = True


def _client(jobs: DiarizeJobs | None, embedder: EmbedService | None) -> TestClient:
    app = create_worker_app(
        TOKEN,
        gpu_info=lambda: GpuInfo(False),
        speech=SpeechService(lambda: LoadedModel(None, "")),  # type: ignore[arg-type]
        diarize_jobs=jobs,
        embedder=embedder,
    )
    return TestClient(app)


def test_the_routes_run_a_job_and_embed() -> None:
    embedder = _Embedder()
    jobs = DiarizeJobs(lambda: _Diarizer(), new_id=lambda: "j1")
    with _client(jobs, EmbedService(lambda: embedder)) as client:
        started = client.post("/diarize", params={"min_speakers": 2}, content=b"RIFF", headers=AUTH)
        _wait(jobs, "j1")
        status = client.get("/diarize/j1", headers=AUTH).json()
        cancelled = client.delete("/diarize/j1", headers=AUTH)
        vector = client.post("/embed", content=np.zeros(160, dtype="<f4").tobytes(), headers=AUTH)
        health = client.get("/health", headers=AUTH).json()

    assert (started.status_code, started.json()) == (202, {"job_id": "j1"})
    assert status == {
        "state": "done",
        "turns": [
            {"start": 0.0, "end": 2.5, "speaker_index": 0},
            {"start": 2.5, "end": 4.0, "speaker_index": 1},
        ],
        "message": None,
    }
    assert cancelled.status_code == 204
    assert vector.json() == {"vector": [160.0, 1.5]}
    assert health["capabilities"] == ["speech", "speakers"]
    assert embedder.closed  # released when the worker stops


def test_bad_requests_and_a_worker_without_speakers() -> None:
    with _client(DiarizeJobs(lambda: _Diarizer()), EmbedService(_Embedder)) as client:
        assert client.post("/diarize", content=b"", headers=AUTH).status_code == 422
        assert client.post("/embed", content=b"123", headers=AUTH).status_code == 422
        assert client.get("/diarize/nope", headers=AUTH).status_code == 404
        assert client.delete("/diarize/nope", headers=AUTH).status_code == 404
        assert client.post("/diarize", content=b"x").status_code == 401
    with _client(None, None) as client:
        assert client.post("/diarize", content=b"x", headers=AUTH).json()["error"]["code"] == (
            "worker_speakers_unavailable"
        )
        assert client.post("/embed", content=b"1234", headers=AUTH).status_code == 503
        assert client.get("/health", headers=AUTH).json()["capabilities"] == ["speech"]
