from __future__ import annotations

from urllib.parse import quote

import numpy as np
from fastapi.testclient import TestClient

from vozata.api.system_info import GpuInfo
from vozata.domain import TranscriptionResult, Word
from vozata.worker.app import create_worker_app
from vozata.worker.speech import LoadedModel, SpeechService

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _Scripted:
    def __init__(self, result: TranscriptionResult) -> None:
        self.result = result
        self.calls: list[tuple[np.ndarray, str | None, str | None, str | None]] = []

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append((samples, language, hints, prompt))
        return self.result

    def close(self) -> None:
        pass


RESULT = TranscriptionResult(
    (Word(" Olá", 0.0, 0.5, 0.91), Word(" mundo", 0.5, 1.0, 0.42)), "pt", -0.27
)


def _client(transcriber: _Scripted) -> TestClient:
    speech = SpeechService(lambda: LoadedModel(transcriber, "large-v3-turbo"))
    app = create_worker_app(TOKEN, gpu_info=lambda: GpuInfo(False), speech=speech)
    return TestClient(app)


def _body(samples: np.ndarray) -> bytes:
    return samples.astype("<f4").tobytes()


def test_samples_language_hints_and_prompt_reach_the_transcriber() -> None:
    transcriber = _Scripted(RESULT)
    samples = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)

    response = _client(transcriber).post(
        "/transcribe",
        params={"language": "pt"},
        content=_body(samples),
        headers={
            **AUTH,
            "Content-Type": "application/octet-stream",
            "X-Hints": quote("VozAta, Ação"),
            "X-Prompt": quote("reunião de ontem"),
        },
    )

    assert response.status_code == 200
    got, language, hints, prompt = transcriber.calls[0]
    np.testing.assert_array_equal(got, samples)
    assert got.dtype == np.float32
    assert (language, hints, prompt) == ("pt", "VozAta, Ação", "reunião de ontem")


def test_the_reply_carries_probabilities_and_the_mean_log_probability() -> None:
    response = _client(_Scripted(RESULT)).post(
        "/transcribe", content=_body(np.zeros(160, dtype=np.float32)), headers=AUTH
    )

    assert response.json() == {
        "words": [
            {"text": " Olá", "start": 0.0, "end": 0.5, "probability": 0.91},
            {"text": " mundo", "start": 0.5, "end": 1.0, "probability": 0.42},
        ],
        "language": "pt",
        "avg_logprob": -0.27,
    }


def test_no_language_hints_or_prompt_mean_none() -> None:
    transcriber = _Scripted(TranscriptionResult((), None))

    response = _client(transcriber).post(
        "/transcribe",
        params={"language": ""},
        content=_body(np.zeros(160, dtype=np.float32)),
        headers=AUTH,
    )

    assert response.json() == {"words": [], "language": None, "avg_logprob": None}
    assert transcriber.calls[0][1:] == (None, None, None)


def test_a_body_that_is_not_float32_is_refused() -> None:
    transcriber = _Scripted(RESULT)

    response = _client(transcriber).post("/transcribe", content=b"\x00" * 7, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "worker_invalid_audio"
    assert transcriber.calls == []


def test_an_empty_body_is_refused() -> None:
    response = _client(_Scripted(RESULT)).post("/transcribe", content=b"", headers=AUTH)

    assert response.status_code == 422


def test_transcribe_needs_the_token() -> None:
    response = _client(_Scripted(RESULT)).post("/transcribe", content=b"\x00" * 8)

    assert response.status_code == 401


def test_stopping_the_worker_releases_the_model() -> None:
    closed: list[bool] = []
    transcriber = _Scripted(RESULT)
    transcriber.close = lambda: closed.append(True)  # type: ignore[method-assign]

    with _client(transcriber) as client:
        client.post("/transcribe", content=_body(np.zeros(160, dtype=np.float32)), headers=AUTH)

    assert closed == [True]


def test_health_lists_the_model_after_the_first_request() -> None:
    client = _client(_Scripted(RESULT))
    before = client.get("/health", headers=AUTH).json()["models"]

    client.post("/transcribe", content=_body(np.zeros(160, dtype=np.float32)), headers=AUTH)

    assert (before, client.get("/health", headers=AUTH).json()["models"]) == (
        [],
        ["large-v3-turbo"],
    )
