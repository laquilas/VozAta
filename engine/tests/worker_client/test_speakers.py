"""The engine's speaker providers over the worker (phase 45)."""

from __future__ import annotations

from pathlib import Path

import httpx
import numpy as np
import pytest

from vozata.domain import SpeakerTurn
from vozata.ports import DiarizationError, WorkerUnreachableError
from vozata.worker_client.client import WorkerClient, WorkerRequestError
from vozata.worker_client.speakers import WorkerDiarizer, WorkerEmbedder

URL = "http://gpu-pc:8766"
LOCAL_TURNS = [SpeakerTurn(0, 1, 0)]


class _Notices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fallback(self, task: str, host: str) -> None:
        self.calls.append((task, host))


class _LocalDiarizer:
    def __init__(self) -> None:
        self.cancelled = self.closed = False

    def diarize(self, wav: Path, low: int | None, high: int | None) -> list[SpeakerTurn]:
        return LOCAL_TURNS

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> None:
        self.closed = True


class _Worker:
    """A scripted worker: `/health`, a diarize job that answers `states`, `/embed`."""

    def __init__(self, states: list[dict], embed_error: Exception | None = None) -> None:
        self.states = list(states)
        self.requests: list[httpx.Request] = []
        self.embed_error = embed_error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={})
        if path == "/diarize":
            return httpx.Response(202, json={"job_id": "j1"})
        if path == "/diarize/j1" and request.method == "GET":
            return httpx.Response(200, json=self.states.pop(0))
        if path == "/diarize/j1":
            return httpx.Response(204)
        if self.embed_error is not None:
            raise self.embed_error
        return httpx.Response(200, json={"vector": [0.5, -1.0]})


def _client(worker: _Worker) -> WorkerClient:
    return WorkerClient(URL, "t", transport=httpx.MockTransport(worker))


def _wav(tmp_path: Path) -> Path:
    path = tmp_path / "system.wav"
    path.write_bytes(b"RIFF....")
    return path


def test_a_job_on_the_worker_is_polled_until_done(tmp_path: Path) -> None:
    worker = _Worker(
        [
            {"state": "running", "turns": [], "message": None},
            {
                "state": "done",
                "turns": [{"start": 0, "end": 2.5, "speaker_index": 1}],
                "message": None,
            },
        ]
    )
    slept: list[float] = []
    diarizer = WorkerDiarizer(_client(worker), _LocalDiarizer, _Notices(), sleep=slept.append)

    turns = diarizer.diarize(_wav(tmp_path), 2, None)

    assert turns == [SpeakerTurn(0.0, 2.5, 1)]
    assert slept == [1.0]
    upload = next(r for r in worker.requests if r.url.path == "/diarize")
    assert (upload.content, dict(upload.url.params)) == (b"RIFF....", {"min_speakers": "2"})


def test_a_failed_job_is_a_diarization_error(tmp_path: Path) -> None:
    worker = _Worker([{"state": "failed", "turns": [], "message": "no GPU memory"}])

    with pytest.raises(DiarizationError, match="no GPU memory"):
        WorkerDiarizer(_client(worker), _LocalDiarizer, _Notices()).diarize(
            _wav(tmp_path), None, None
        )


def test_cancel_cancels_the_job_on_the_worker(tmp_path: Path) -> None:
    worker = _Worker([{"state": "running", "turns": [], "message": None}] * 3)
    diarizer: WorkerDiarizer

    def cancel_while_waiting(seconds: float) -> None:
        diarizer.cancel()

    diarizer = WorkerDiarizer(
        _client(worker), _LocalDiarizer, _Notices(), sleep=cancel_while_waiting
    )

    with pytest.raises(DiarizationError, match="cancelled"):
        diarizer.diarize(_wav(tmp_path), None, None)
    with pytest.raises(DiarizationError):
        diarizer.diarize(_wav(tmp_path), None, None)  # a cancel is final

    deletes = [r for r in worker.requests if r.method == "DELETE"]
    assert deletes and deletes[0].url.path == "/diarize/j1"


def test_a_lost_worker_falls_back_to_this_pc_once_with_a_notice(tmp_path: Path) -> None:
    def gone(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={})
        raise httpx.ConnectError("refused")

    notices = _Notices()
    built: list[_LocalDiarizer] = []

    def local() -> _LocalDiarizer:
        built.append(_LocalDiarizer())
        return built[-1]

    diarizer = WorkerDiarizer(
        WorkerClient(URL, "t", transport=httpx.MockTransport(gone)), local, notices
    )

    assert diarizer.diarize(_wav(tmp_path), None, None) == LOCAL_TURNS
    assert diarizer.diarize(_wav(tmp_path), None, None) == LOCAL_TURNS
    diarizer.cancel()
    diarizer.close()

    assert notices.calls == [("speakers", "gpu-pc")]
    assert len(built) == 1 and built[0].cancelled and built[0].closed


def test_a_worker_error_is_a_diarization_error(tmp_path: Path) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={})
        return httpx.Response(507, json={"error": {"code": "worker_disk_full"}})

    diarizer = WorkerDiarizer(
        WorkerClient(URL, "t", transport=httpx.MockTransport(refused)), _LocalDiarizer, _Notices()
    )

    with pytest.raises(DiarizationError, match="worker_disk_full"):
        diarizer.diarize(_wav(tmp_path), None, None)


def test_a_worker_without_speakers_is_replaced_by_this_pc(tmp_path: Path) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={})
        return httpx.Response(503, json={"error": {"code": "worker_speakers_unavailable"}})

    notices = _Notices()
    diarizer = WorkerDiarizer(
        WorkerClient(URL, "t", transport=httpx.MockTransport(unavailable)), _LocalDiarizer, notices
    )

    assert diarizer.diarize(_wav(tmp_path), None, None) == LOCAL_TURNS
    assert notices.calls == [("speakers", "gpu-pc")]


def test_the_embedder_uses_the_worker_then_this_pc_when_it_is_lost() -> None:
    worker = _Worker([])
    notices = _Notices()

    class _Local:
        closed = False

        def embed(self, samples: np.ndarray) -> np.ndarray:
            return np.array([9.0], dtype=np.float32)

        def close(self) -> None:
            _Local.closed = True

    embedder = WorkerEmbedder(_client(worker), _Local, notices)
    first = embedder.embed(np.ones(160, dtype=np.float32))
    worker.embed_error = httpx.ConnectError("refused")
    second = embedder.embed(np.ones(160, dtype=np.float32))
    third = embedder.embed(np.ones(160, dtype=np.float32))
    embedder.close()

    np.testing.assert_array_equal(first, [0.5, -1.0])
    np.testing.assert_array_equal(second, [9.0])
    np.testing.assert_array_equal(third, [9.0])
    assert notices.calls == [("speakers", "gpu-pc")] and _Local.closed
    sent = next(r for r in worker.requests if r.url.path == "/embed")
    assert len(sent.content) == 160 * 4


def test_an_unknown_error_reply_names_the_status() -> None:
    def odd(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={})
            if request.url.path == "/health"
            else httpx.Response(500, text="boom")
        )

    with pytest.raises(WorkerRequestError, match="HTTP 500"):
        WorkerClient(URL, "t", transport=httpx.MockTransport(odd)).embed(
            np.ones(4, dtype=np.float32)
        )


def test_a_worker_off_at_the_start_is_unreachable() -> None:
    def off(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(WorkerUnreachableError):
        WorkerClient(URL, "t", transport=httpx.MockTransport(off)).embed(
            np.ones(4, dtype=np.float32)
        )
