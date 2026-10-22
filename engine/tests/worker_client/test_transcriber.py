from __future__ import annotations

import httpx
import numpy as np

from tests.transcription.contract import SAMPLE_RATE, check_transcriber_contract
from vozata.domain import TranscriptionResult, Word
from vozata.ports import WorkerUnreachableError
from vozata.worker_client.client import WorkerClient
from vozata.worker_client.transcriber import WorkerTranscriber

URL = "http://gpu-pc:8766"
LOCAL_RESULT = TranscriptionResult((Word(" local", 0.0, 0.5, 0.7),), "pt")


class _Notices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fallback(self, task: str, host: str) -> None:
        self.calls.append((task, host))


class _Local:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        self.calls += 1
        return LOCAL_RESULT

    def close(self) -> None:
        self.closed = True


class _Client:
    """A worker client scripted with results or errors."""

    host = "gpu-pc"

    def __init__(self, *answers: TranscriptionResult | Exception) -> None:
        self._answers = list(answers)
        self.calls = 0
        self.closed = False

    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None, prompt: str | None
    ) -> TranscriptionResult:
        self.calls += 1
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:
        self.closed = True


REMOTE = TranscriptionResult((Word(" remoto", 0.0, 0.5, 0.9),), "pt", -0.1)
CHUNK = np.full(160, 0.1, dtype=np.float32)


def _transcriber(client: _Client) -> tuple[WorkerTranscriber, list[_Local], _Notices]:
    built: list[_Local] = []
    notices = _Notices()

    def local() -> _Local:
        built.append(_Local())
        return built[-1]

    return WorkerTranscriber(client, local, notices), built, notices  # type: ignore[arg-type]


def test_the_worker_transcribes_while_it_answers() -> None:
    transcriber, built, notices = _transcriber(_Client(REMOTE, REMOTE))

    results = [transcriber.transcribe(CHUNK, "pt"), transcriber.transcribe(CHUNK, "pt")]

    assert results == [REMOTE, REMOTE]
    assert (built, notices.calls, transcriber.remote) == ([], [], True)


def test_losing_the_worker_switches_to_this_pc_once_and_says_so() -> None:
    client = _Client(REMOTE, WorkerUnreachableError("gpu-pc", "refused"))
    transcriber, built, notices = _transcriber(client)

    first = transcriber.transcribe(CHUNK, "pt")
    second = transcriber.transcribe(CHUNK, "pt")
    third = transcriber.transcribe(CHUNK, "pt")

    assert (first, second, third) == (REMOTE, LOCAL_RESULT, LOCAL_RESULT)
    assert len(built) == 1 and built[0].calls == 2
    assert client.calls == 2  # later chunks never try the worker again
    assert notices.calls == [("speech", "gpu-pc")]
    assert transcriber.remote is False


def test_close_closes_the_client_and_the_local_transcriber() -> None:
    transcriber, built, _ = _transcriber(_Client(WorkerUnreachableError("gpu-pc", "x")))
    transcriber.transcribe(CHUNK, None)

    transcriber.close()

    assert built[0].closed


def test_close_without_a_fallback_builds_nothing() -> None:
    client = _Client()
    transcriber, built, _ = _transcriber(client)

    transcriber.close()

    assert (client.closed, built) == (True, [])


def _scripted_worker(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"worker": "ok"})
    seconds = len(request.content) / 4 / SAMPLE_RATE
    words = [{"text": " olá", "start": 0.1, "end": min(0.6, seconds), "probability": 0.93}]
    return httpx.Response(200, json={"words": words, "language": "pt", "avg_logprob": -0.1})


def test_the_worker_transcriber_honours_the_contract() -> None:
    client = WorkerClient(URL, "t", transport=httpx.MockTransport(_scripted_worker))
    transcriber = WorkerTranscriber(client, _Local, _Notices())
    speech = np.sin(np.linspace(0, 2000, SAMPLE_RATE)).astype(np.float32)

    check_transcriber_contract(transcriber, speech, "pt")
