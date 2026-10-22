from __future__ import annotations

import threading
import time

import numpy as np

from vozata.domain import TranscriptionResult, Word
from vozata.worker.speech import LoadedModel, SpeechService


class _Recording:
    """A transcriber that records its calls and how many ran at once."""

    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[tuple[np.ndarray, str | None, str | None, str | None]] = []
        self.closed = False
        self._delay = delay
        self._running = 0
        self.max_running = 0
        self._guard = threading.Lock()

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        with self._guard:
            self._running += 1
            self.max_running = max(self.max_running, self._running)
        time.sleep(self._delay)
        self.calls.append((samples, language, hints, prompt))
        with self._guard:
            self._running -= 1
        return TranscriptionResult((Word("oi", 0.0, 0.4, 0.9),), "pt", -0.3)

    def close(self) -> None:
        self.closed = True


def _service(transcriber: _Recording) -> tuple[SpeechService, list[int]]:
    built: list[int] = []

    def factory() -> LoadedModel:
        built.append(1)
        return LoadedModel(transcriber, "large-v3-turbo")

    return SpeechService(factory), built


def test_nothing_is_loaded_before_the_first_request() -> None:
    service, built = _service(_Recording())

    assert (service.models(), built) == ([], [])


def test_the_model_is_built_once_and_kept() -> None:
    transcriber = _Recording()
    service, built = _service(transcriber)
    samples = np.zeros(1600, dtype=np.float32)

    service.transcribe(samples, "pt", None, None)
    result = service.transcribe(samples, None, "VozAta", "antes")

    assert len(built) == 1
    assert service.models() == ["large-v3-turbo"]
    assert result == TranscriptionResult((Word("oi", 0.0, 0.4, 0.9),), "pt", -0.3)
    assert transcriber.calls[1][1:] == (None, "VozAta", "antes")


def test_requests_run_one_at_a_time() -> None:
    transcriber = _Recording(delay=0.05)
    service, built = _service(transcriber)
    samples = np.zeros(160, dtype=np.float32)
    threads = [
        threading.Thread(target=service.transcribe, args=(samples, None, None, None))
        for _ in range(3)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert (transcriber.max_running, len(transcriber.calls), len(built)) == (1, 3, 1)


def test_close_releases_the_model() -> None:
    transcriber = _Recording()
    service, _ = _service(transcriber)
    service.transcribe(np.zeros(160, dtype=np.float32), None, None, None)

    service.close()

    assert transcriber.closed
    assert service.models() == []


def test_closing_an_unused_service_does_nothing() -> None:
    service, built = _service(_Recording())

    service.close()

    assert built == []
