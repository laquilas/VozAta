"""One transcriber reused by consecutive `serve` sessions (`WHISPER_KEEP_LOADED`, phase 26)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from vozata.domain import TranscriptionResult
from vozata.ports import Transcriber


class SharedTranscriber:
    """Loads the transcriber on the first `lease()` and keeps it while leases end with `keep`.

    The VRAM rule still holds: a lease that ends without `keep` (minutes follow) and `release()`
    (before `POST /sessions/{id}/minutes`, at shutdown) unload it; the next lease loads it again.
    """

    def __init__(self, factory: Callable[[], Transcriber]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._model: Transcriber | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def lease(self, *, keep: bool) -> Transcriber:
        """The shared transcriber; closing the lease unloads it unless `keep`."""
        with self._lock:
            if self._model is None:
                self._model = self._factory()
            return _Lease(self, self._model, keep)

    def release(self) -> None:
        """Unload the transcriber now (no-op when it is not loaded)."""
        with self._lock:
            model, self._model = self._model, None
        if model is not None:
            model.close()


class _Lease:
    def __init__(self, owner: SharedTranscriber, model: Transcriber, keep: bool) -> None:
        self._owner = owner
        self._model = model
        self._keep = keep

    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None = None
    ) -> TranscriptionResult:
        return self._model.transcribe(samples, language, hints)

    def close(self) -> None:
        if not self._keep:
            self._owner.release()
