"""A live recording's hold on the GPU gate (phase 40): taken when its first model loads."""

from __future__ import annotations

import contextlib
import logging
import threading

from vozata.processing.gpu_gate import GpuGate, GpuUsage, GpuUser

log = logging.getLogger(__name__)

TURN_WARNING_SECONDS = 300.0  # the previous model load may be a cold download (20+ min)


class ModelLoadSkipped(Exception):  # noqa: N818 - a skip, not an error
    """A live model load skipped because its session stopped first (not a failure)."""


class LiveGpuLease:
    """`hold_speech()` / `hold_speakers()` take `gate.priority(GpuUser.LIVE)` once, before a live
    model that runs on the local GPU loads (pre-empting the queue's running GPU step, <= 5 s);
    `release()` gives it back once the live models are closed. Only the models the live session
    loads count: the speech model when `usage.speech`, the live speaker embedder when
    `usage.live_speakers` (post-session diarization on the GPU does not). Nothing is held without
    a gate. After `release()`, a hold does nothing (a load finishing after Stop)."""

    def __init__(self, gate: GpuGate | None, usage: GpuUsage | None) -> None:
        self._gate = gate if usage is not None else None
        self._speech = usage is not None and usage.speech
        self._speakers = usage is not None and usage.live_speakers
        self._lock = threading.Lock()
        self._held: contextlib.ExitStack | None = None
        self._released = False

    def hold_speech(self) -> None:
        """Before the live speech model loads."""
        if self._speech:
            self._hold()

    def hold_speakers(self) -> None:
        """Before the live speaker embedder loads."""
        if self._speakers:
            self._hold()

    def _hold(self) -> None:
        if self._gate is None:
            return
        with self._lock:  # a second loader waits until the first one holds the gate
            if self._held is not None or self._released:
                return
            held = contextlib.ExitStack()
            held.enter_context(self._gate.priority(GpuUser.LIVE))
            self._held = held

    def release(self) -> None:
        with self._lock:
            held, self._held = self._held, None
            self._released = True
        if held is not None:
            held.close()


class LiveModelTurn:
    """One live session's models at a time (phase 40): a new session's model load waits until the
    previous session's abandoned pipeline closed (its model load may still run after Stop), so
    two live Whisper models never coexist. Capture never waits. `wait()` has no timeout but
    logs a warning every `warn_every` seconds."""

    def __init__(self, warn_every: float = TURN_WARNING_SECONDS) -> None:
        self._warn_every = warn_every
        self._lock = threading.Lock()
        self._closing: threading.Event | None = None

    def wait(self) -> None:
        """Block until the last stopped session's live models are closed."""
        with self._lock:
            closing = self._closing
        if closing is None:
            return
        waited = 0.0
        while not closing.wait(self._warn_every):
            waited += self._warn_every
            log.warning(
                "still waiting for the previous recording's live models to close (%.0f s)", waited
            )

    def stopping(self, closed: threading.Event) -> None:
        """A session stopped; `closed` is set once its live models are closed."""
        with self._lock:
            self._closing = closed
