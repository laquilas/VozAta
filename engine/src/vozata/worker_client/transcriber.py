"""`Transcriber` over the VozAta worker, with a switch to this PC when the worker is lost."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from vozata.domain import TranscriptionResult
from vozata.ports import FallbackNotices, Transcriber, WorkerUnreachableError
from vozata.worker_client.client import WorkerClient


class WorkerTranscriber:
    """Whisper on the worker PC, with the same results as the local one (real word
    probabilities, `avg_logprob`, hints apart from the prompt).

    Losing the worker mid-session builds the local transcriber once, says so through `notices`
    and transcribes that chunk and every later one on this PC: the recording goes on (phase 26).
    """

    def __init__(
        self,
        client: WorkerClient,
        local_factory: Callable[[], Transcriber],
        notices: FallbackNotices,
    ) -> None:
        self._client = client
        self._local_factory = local_factory
        self._notices = notices
        self._local: Transcriber | None = None

    @property
    def remote(self) -> bool:
        """True while speech still runs on the worker (the GPU gate's `speech_remote`)."""
        return self._local is None

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self._local is None:
            try:
                return self._client.transcribe(samples, language, hints, prompt)
            except WorkerUnreachableError as error:
                self._notices.fallback("speech", error.host)  # first: it may take the GPU gate
                self._local = self._local_factory()
        return self._local.transcribe(samples, language, hints, prompt)

    def close(self) -> None:
        self._client.close()
        if self._local is not None:
            self._local.close()
