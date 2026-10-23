"""The worker's Whisper: loaded on the first request, then kept between meetings (phase 44)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from vozata.domain import TranscriptionResult
from vozata.ports import Transcriber


@dataclass(frozen=True)
class LoadedModel:
    transcriber: Transcriber
    name: str  # what `/health` lists, e.g. `large-v3-turbo`


class SpeechService:
    """One transcriber for every engine that calls this worker, one request at a time.

    Whisper is not safe to call from two threads, and one GPU gains nothing from running two
    chunks at once, so a lock serializes requests (the engine's chunks are a few seconds each).
    """

    def __init__(self, factory: Callable[[], LoadedModel]) -> None:
        self._factory = factory
        self._loaded: LoadedModel | None = None
        self._lock = threading.Lock()

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None,
        prompt: str | None,
    ) -> TranscriptionResult:
        with self._lock:
            if self._loaded is None:
                self._loaded = self._factory()
            return self._loaded.transcriber.transcribe(samples, language, hints, prompt)

    def models(self) -> list[str]:
        loaded = self._loaded
        return [loaded.name] if loaded is not None else []

    def close(self) -> None:
        with self._lock:
            if self._loaded is not None:
                self._loaded.transcriber.close()
                self._loaded = None
