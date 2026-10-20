"""A live recording's hold on the GPU gate (phase 40): taken when its first model loads."""

from __future__ import annotations

import contextlib
import threading

from vozata.processing.gpu_gate import GpuGate, GpuUsage, GpuUser


class LiveGpuLease:
    """`hold()` takes `gate.priority(GpuUser.LIVE)` once, before the live speech or speaker model
    loads (pre-empting the queue's running GPU step, ≤ 5 s); `release()` gives it back once the
    live models are closed. Nothing is held without a gate or when neither live model uses the
    GPU. After `release()`, `hold()` does nothing (a load finishing after Stop)."""

    def __init__(self, gate: GpuGate | None, usage: GpuUsage | None) -> None:
        self._gate = gate if usage is not None and (usage.speech or usage.speakers) else None
        self._lock = threading.Lock()
        self._held: contextlib.ExitStack | None = None
        self._released = False

    def hold(self) -> None:
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
