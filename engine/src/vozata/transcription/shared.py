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
    Leases are counted (phase 40: a queued transcription and a live session may overlap for a
    moment): an unload asked for while a lease is open happens when the last open lease closes,
    never under a lease that is still transcribing.
    """

    def __init__(self, factory: Callable[[], Transcriber]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._model: Transcriber | None = None
        self._open = 0
        self._unload = False  # an unload was asked for while leases were open

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def lease(self, *, keep: bool, keep_when: Callable[[], bool] = lambda: False) -> Transcriber:
        """The shared transcriber; closing the lease unloads it unless `keep`, or unless
        `keep_when()` is true at that moment (phase 40: a transcribe step cancelled by a live
        start keeps the model, since the live session leases it next)."""
        with self._lock:
            if self._model is None:
                self._model = self._factory()
            self._open += 1
            return _Lease(self, self._model, keep, keep_when)

    def release(self) -> None:
        """Unload the transcriber now, or when the last open lease closes (no-op when nothing
        is loaded)."""
        self._unload_when_free(True)

    def _closed(self, keep: bool) -> None:
        with self._lock:
            self._open -= 1
        self._unload_when_free(not keep)

    def _unload_when_free(self, unload: bool) -> None:
        with self._lock:
            self._unload = self._unload or unload
            if self._open > 0 or not self._unload:
                return
            model, self._model = self._model, None
            self._unload = False
        if model is not None:
            model.close()


class _Lease:
    def __init__(
        self,
        owner: SharedTranscriber,
        model: Transcriber,
        keep: bool,
        keep_when: Callable[[], bool],
    ) -> None:
        self._owner = owner
        self._model = model
        self._keep = keep
        self._keep_when = keep_when
        self._closed = False

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        return self._model.transcribe(samples, language, hints, prompt)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._owner._closed(self._keep or self._keep_when())
