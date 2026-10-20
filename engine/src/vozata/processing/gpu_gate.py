"""GPU arbitration: live recording, Ask and Config tests pre-empt the queue's GPU work."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import StrEnum

from vozata.config import Settings
from vozata.domain import WhisperDevice
from vozata.processing.cancel import CancelToken, StepCancelled

log = logging.getLogger(__name__)


class GpuUser(StrEnum):
    LIVE = "live"
    ASK = "ask"
    CHECK = "check"
    QUEUE = "queue"


@dataclass(frozen=True)
class GpuUsage:
    speech: bool
    speakers: bool  # post-session or live diarization
    llm: bool
    live_speakers: bool = False  # the live speaker embedder (live diarization only)


def gpu_usage(settings: Settings, cuda: bool) -> GpuUsage:
    """Which model families would run on the GPU with these settings."""
    speech = (
        settings.stt_provider == "faster_whisper"
        and settings.whisper_device != WhisperDevice.CPU
        and cuda
    )
    wants_speakers = settings.diarization_enabled or settings.live_diarization_enabled
    speakers_on_gpu = settings.diarization_device != WhisperDevice.CPU and cuda
    speakers = wants_speakers and speakers_on_gpu
    live_speakers = settings.live_diarization_enabled and speakers_on_gpu
    llm = settings.llm_provider == "ollama" and cuda
    return GpuUsage(speech=speech, speakers=speakers, llm=llm, live_speakers=live_speakers)


class GpuGate:
    def __init__(self, cancel_timeout: float = 5.0) -> None:
        self._cancel_timeout = cancel_timeout
        self._cond = threading.Condition()
        self._holders = 0
        self._running: CancelToken | None = None

    @property
    def priority_held(self) -> bool:
        with self._cond:
            return self._holders > 0

    def priority(self, user: GpuUser) -> AbstractContextManager[None]:
        return self._priority(user)

    def queue_step(
        self, token: CancelToken, on_wait: Callable[[], None]
    ) -> AbstractContextManager[None]:
        return self._queue_step(token, on_wait)

    def _wake(self) -> None:
        with self._cond:
            self._cond.notify_all()

    @contextmanager
    def _priority(self, user: GpuUser) -> Iterator[None]:
        with self._cond:
            self._holders += 1
            running = self._running
        try:
            if running is not None:
                running.cancel()
                with self._cond:
                    left = self._cond.wait_for(
                        lambda: self._running is not running, self._cancel_timeout
                    )
                if not left:
                    log.warning(
                        "queue GPU step did not stop within %.1fs; %s proceeds",
                        self._cancel_timeout,
                        user.value,
                    )
            yield
        finally:
            with self._cond:
                self._holders -= 1
                self._cond.notify_all()

    @contextmanager
    def _queue_step(self, token: CancelToken, on_wait: Callable[[], None]) -> Iterator[None]:
        token.raise_if_cancelled()
        with self._cond:
            blocked = self._holders > 0
        if blocked:
            on_wait()
        unregister = token.on_cancel(self._wake)
        try:
            with self._cond:
                self._cond.wait_for(lambda: self._holders == 0 or token.cancelled)
                if token.cancelled:
                    raise StepCancelled
                self._running = token
        finally:
            unregister()
        try:
            yield
        finally:
            with self._cond:
                self._running = None
                self._cond.notify_all()
