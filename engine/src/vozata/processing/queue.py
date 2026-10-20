"""Single-worker FIFO queue that processes finished meetings in the background."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.gpu_gate import GpuGate
from vozata.processing.job import ProcessingJob, Step, StepKind, shown_kind

log = logging.getLogger(__name__)

State = Literal["queued", "running", "paused", "done", "failed"]


@dataclass(frozen=True)
class ProcessingState:
    session_id: str
    state: State
    percent: int
    step: StepKind | None
    position: int | None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state,
            "percent": self.percent,
            "step": self.step.value if self.step is not None else None,
        }
        if self.state == "queued":
            payload["position"] = self.position
        return payload


class ProcessingQueue:
    def __init__(
        self,
        gate: GpuGate,
        publish: Callable[[ProcessingState], None],
        clock: Callable[[], float] = time.monotonic,
        progress_interval: float = 1.0,
    ) -> None:
        self._gate = gate
        self._publish = publish
        self._clock = clock
        self._interval = progress_interval
        self._cond = threading.Condition()
        self._waiting: deque[ProcessingJob] = deque()
        self._states: dict[str, ProcessingState] = {}
        self._current: str | None = None
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="processing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(5.0)

    def enqueue(self, job: ProcessingJob) -> bool:
        """Queue `job`; False when its meeting is already queued or running."""
        with self._cond:
            if job.session_id in self._states:
                log.warning("meeting %s is already in the processing queue", job.session_id)
                return False
            self._waiting.append(job)
            state = ProcessingState(job.session_id, "queued", 0, None, len(self._waiting))
            self._states[job.session_id] = state
            self._cond.notify_all()
        self._emit(state)
        return True

    def _emit(self, state: ProcessingState) -> None:
        try:
            self._publish(state)
        except Exception:
            log.exception("publishing the processing state of %s failed", state.session_id)

    def state(self, session_id: str) -> ProcessingState | None:
        with self._cond:
            return self._states.get(session_id)

    def contains(self, session_id: str) -> bool:
        return self.state(session_id) is not None

    def pending(self) -> list[ProcessingState]:
        with self._cond:
            ordered = [job.session_id for job in self._waiting]
            running = [s for sid, s in self._states.items() if sid == self._current]
            return running + [self._states[sid] for sid in ordered]

    def wait_idle(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not self._states, timeout)

    # -- worker ---------------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stopping or self._waiting)
                if self._stopping:
                    return
                job = self._waiting.popleft()
                self._current = job.session_id
                moved = self._renumber()
            try:
                for state in moved:
                    self._emit(state)
                self._process(job)
            except Exception:
                log.exception("processing of meeting %s crashed", job.session_id)
                self._set(job.session_id, "failed")
            finally:
                with self._cond:
                    self._states.pop(job.session_id, None)
                    self._current = None
                    self._cond.notify_all()

    def _renumber(self) -> list[ProcessingState]:
        """Give the queued jobs their new positions (caller holds the lock)."""
        moved = []
        for position, waiting in enumerate(self._waiting, start=1):
            state = replace(self._states[waiting.session_id], position=position)
            self._states[waiting.session_id] = state
            moved.append(state)
        return moved

    def _set(self, session_id: str, state: State, **changes: Any) -> None:
        with self._cond:
            old = self._states[session_id]
            new = replace(old, state=state, position=None, **changes)
            self._states[session_id] = new
            if new == old:
                return
        self._emit(new)

    def _process(self, job: ProcessingJob) -> None:
        total = sum(step.weight for step in job.steps) or 1.0
        done_weight = 0.0
        last = {"percent": 0, "at": self._clock()}
        self._set(job.session_id, "running", step=shown_kind(job.steps, 0))
        try:
            job.before()
        except Exception:
            log.exception("preparing the processing of meeting %s failed", job.session_id)

        def percent_of(fraction: float) -> int:
            return int(round(min(done_weight + fraction * current.weight, total) / total * 100))

        for index, step in enumerate(job.steps):
            current = step
            kind = shown_kind(job.steps, index)

            def progress(fraction: float, kind: StepKind | None = kind) -> None:
                value = percent_of(max(0.0, min(1.0, fraction)))
                now = self._clock()
                if value > last["percent"] and now - last["at"] >= self._interval:
                    last["percent"], last["at"] = value, now
                    self._set(job.session_id, "running", percent=value, step=kind)

            self._set(job.session_id, "running", step=kind)
            self._run_step(job, step, kind, progress)
            done_weight += step.weight
            value = max(last["percent"], percent_of(0.0))
            last["percent"], last["at"] = value, self._clock()
            self._set(job.session_id, "running", percent=value, step=kind)

        self._set(job.session_id, "done", percent=100, step=None)
        try:
            job.on_finished()
        except Exception:
            log.exception("finishing meeting %s failed", job.session_id)
            self._set(job.session_id, "failed")

    def _run_step(
        self,
        job: ProcessingJob,
        step: Step,
        kind: StepKind | None,
        progress: Callable[[float], None],
    ) -> None:
        """Run `step` until it completes or fails; a pre-empted GPU step is redone."""
        sid = job.session_id
        while True:
            token = CancelToken()  # a cancelled token stays cancelled: one per attempt
            try:
                if step.gpu:
                    on_wait = lambda: self._set(sid, "paused", step=kind)  # noqa: E731
                    with self._gate.queue_step(token, on_wait):
                        self._set(sid, "running", step=kind)
                        step.run(token, progress)
                else:
                    step.run(token, progress)
                return
            except StepCancelled:
                if not (step.gpu and token.cancelled):
                    log.error(
                        "step %s of meeting %s raised a cancel it was not given",
                        step.kind.value,
                        sid,
                    )
                    return
                self._set(sid, "paused", step=kind)
            except Exception:
                log.exception("step %s of meeting %s failed", step.kind.value, sid)
                return
