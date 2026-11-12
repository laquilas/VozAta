"""Mix the selected sources of a recording into its `mic` and `system` channels (phase 65).

Every source pushes its samples on the recording's timeline. `SourceMixer.step` scores the newest
audio first (so a source that starts speaking is selected before its first words are mixed) and
mixes `delay` seconds behind it. Pure numpy and thread-safe; the recording calls `step` from its
mix thread and `push` from the capture threads.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from vozata.domain import Channel
from vozata.recorder.sources import SourceSpec

FRAME_SECONDS = 0.02
WINDOW_SECONDS = 10.0
SPEECH_DB = -50.0  # a frame below this is never speech
FLOOR_MARGIN_DB = 12.0  # ...and must stand this far above the window's noise floor
ACTIVATE_SECONDS = 0.5  # active audio in the window that selects an automatic source
HOLD_SECONDS = 60.0  # an automatic source stays selected this long after its last activity
DUPLICATE_CORRELATION = 0.7  # measured: a mic and its NVIDIA Broadcast copy 0.78, unrelated 0.2
DUPLICATE_MAX_LAG_FRAMES = 5  # a processed copy (noise removal) arrives up to ~100 ms later
SCORE_LATENCY_SECONDS = 0.3  # capture blocks arrive up to this late
MIX_DELAY_SECONDS = 2.0

AUTO, ON, OFF = "auto", "on", "off"
MODES = (AUTO, ON, OFF)
_EPSILON = 1e-12


class SourceBuffer:
    """One source's samples on the timeline (frame `start` onwards) until they are mixed."""

    def __init__(self, start: int, tolerance: int) -> None:
        self._start = start
        self._tolerance = tolerance
        self._data = np.zeros(0, np.float32)
        self.first: int | None = None  # frame of the first block: before it, nothing is known

    @property
    def end(self) -> int:
        return self._start + len(self._data)

    def push(self, samples: np.ndarray, frame: int) -> None:
        """Place a block at `frame`; a small jitter appends it, a larger gap is silence."""
        gap = frame - self.end
        if self.first is None:
            self.first = max(frame, self.end) if gap > self._tolerance else self.end
        parts = [self._data]
        if gap > self._tolerance:
            parts.append(np.zeros(gap, np.float32))
        parts.append(np.asarray(samples, np.float32))
        self._data = np.concatenate(parts)

    def read(self, start: int, end: int) -> np.ndarray:
        """Frames `start`..`end`, zeros where the source has nothing."""
        out = np.zeros(max(0, end - start), np.float32)
        first, last = max(start, self._start), min(end, self.end)
        if last > first:
            out[first - start : last - start] = self._data[first - self._start : last - self._start]
        return out

    def drop_before(self, frame: int) -> None:
        cut = min(max(0, frame - self._start), len(self._data))
        if cut:
            self._data = self._data[cut:]
            self._start += cut
        elif frame > self._start and not len(self._data):
            self._start = frame


def automix(blocks: Sequence[np.ndarray], frame: int) -> np.ndarray:
    """Gain-sharing mix: per frame each block gets its share of the total power.

    One block passes unchanged; a quiet room does not add its noise to a speaking one. The gains
    are interpolated between frame centres (no clicks).
    """
    if not blocks:
        return np.zeros(0, np.float32)
    if len(blocks) == 1:
        return np.asarray(blocks[0], np.float32).copy()
    stack = np.stack([np.asarray(block, np.float32) for block in blocks])
    length = stack.shape[1]
    if length == 0:
        return np.zeros(0, np.float32)
    frames = math.ceil(length / frame)
    padded = np.zeros((len(blocks), frames * frame), np.float32)
    padded[:, :length] = stack
    power = np.mean(np.square(padded.reshape(len(blocks), frames, frame), dtype=np.float64), 2)
    power += _EPSILON
    gains = power / power.sum(axis=0)
    centres = (np.arange(frames) + 0.5) * frame
    positions = np.arange(length)
    smooth = np.stack([np.interp(positions, centres, row) for row in gains])
    return np.clip((stack * smooth).sum(axis=0), -1.0, 1.0).astype(np.float32)


@dataclass(frozen=True)
class SourceScore:
    active_seconds: float
    level_db: float
    silent: bool  # only exact zeros in the window (a blocked mic, an output nobody plays to)
    seen_seconds: float

    @property
    def value(self) -> float:
        """0..1: the share of the window with active audio."""
        return min(1.0, self.active_seconds / WINDOW_SECONDS)


class SourceScorer:
    """Rolling 20 ms frame statistics of every source over the last `window` seconds."""

    def __init__(self, rate: int, window: float = WINDOW_SECONDS) -> None:
        self.frame = max(1, round(rate * FRAME_SECONDS))
        self._rate = rate
        self._size = max(1, round(window / FRAME_SECONDS))
        self._rms: dict[str, deque[float]] = {}
        self._peak: dict[str, deque[float]] = {}
        self._last_active: dict[str, float] = {}

    def update(self, source_id: str, samples: np.ndarray, end_seconds: float) -> None:
        """Add the whole frames of `samples`, the block that ends at `end_seconds`."""
        frames = len(samples) // self.frame
        if frames == 0:
            return
        shaped = np.asarray(samples[: frames * self.frame], np.float64).reshape(frames, self.frame)
        rms = np.sqrt(np.mean(np.square(shaped), axis=1))
        peak = np.max(np.abs(shaped), axis=1)
        rms_queue = self._rms.setdefault(source_id, deque(maxlen=self._size))
        peak_queue = self._peak.setdefault(source_id, deque(maxlen=self._size))
        rms_queue.extend(rms.tolist())
        peak_queue.extend(peak.tolist())
        active = self._active(np.asarray(rms_queue))[-frames:]
        if active.any():
            last = int(np.flatnonzero(active)[-1])
            self._last_active[source_id] = end_seconds - (frames - 1 - last) * FRAME_SECONDS

    def score(self, source_id: str) -> SourceScore:
        rms = np.asarray(self._rms.get(source_id, ()), np.float64)
        if not len(rms):
            return SourceScore(0.0, -90.0, False, 0.0)
        active = self._active(rms)
        level = _db(rms[active]) if active.any() else _db(rms)
        peak = max(self._peak[source_id])
        seen = len(rms) * FRAME_SECONDS
        return SourceScore(
            active_seconds=round(float(active.sum()) * FRAME_SECONDS, 3),
            level_db=round(level, 1),
            silent=peak == 0.0 and seen >= 1.0,
            seen_seconds=round(seen, 3),
        )

    def last_active(self, source_id: str) -> float | None:
        return self._last_active.get(source_id)

    def correlation(self, first: str, second: str) -> float:
        """Best Pearson correlation of the two level envelopes over the common window, within
        ±`DUPLICATE_MAX_LAG_FRAMES` frames; 0 when one of them is flat."""
        a = np.asarray(self._rms.get(first, ()), np.float64)
        b = np.asarray(self._rms.get(second, ()), np.float64)
        size = min(len(a), len(b))
        if size < 10 + 2 * DUPLICATE_MAX_LAG_FRAMES:
            return 0.0
        a, b = a[-size:], b[-size:]
        best = 0.0
        for lag in range(-DUPLICATE_MAX_LAG_FRAMES, DUPLICATE_MAX_LAG_FRAMES + 1):
            x, y = (a[lag:], b[: size - lag]) if lag >= 0 else (a[:lag], b[-lag:])
            if x.std() < _EPSILON or y.std() < _EPSILON:
                continue
            best = max(best, float(np.corrcoef(x, y)[0, 1]))
        return best

    @staticmethod
    def _active(rms: np.ndarray) -> np.ndarray:
        db = 20.0 * np.log10(np.maximum(rms, _EPSILON))
        floor = float(np.percentile(db, 10))
        return (db > SPEECH_DB) & (db > floor + FLOOR_MARGIN_DB)


def _db(rms: np.ndarray) -> float:
    power = float(np.mean(np.square(rms)))
    return max(-90.0, 10.0 * math.log10(power)) if power > 0 else -90.0


@dataclass(frozen=True)
class SelectionChange:
    source_id: str
    selected: bool
    by: str  # "auto" or "user"


class SourceSelector:
    """Which sources are mixed: Auto / On / Off per source, automatic ones by their score."""

    def __init__(
        self,
        specs: Sequence[SourceSpec],
        modes: Mapping[str, str] | None = None,
        selected: Iterable[str] | None = None,
    ) -> None:
        self._specs = {spec.source_id: spec for spec in specs}
        self.modes = {spec.source_id: (modes or {}).get(spec.source_id, AUTO) for spec in specs}
        initial = (
            set(selected) if selected is not None else {s.source_id for s in specs if s.preferred}
        )
        for source_id, mode in self.modes.items():
            if mode == ON:
                initial.add(source_id)
            elif mode == OFF:
                initial.discard(source_id)
        self.selected = {source_id for source_id in initial if source_id in self._specs}
        self.unavailable: set[str] = set()  # failed to open: never mixed

    def of_kind(self, kind: Channel) -> list[str]:
        return [i for i, spec in self._specs.items() if spec.kind == kind and i in self.selected]

    def set_mode(self, source_id: str, mode: str) -> SelectionChange | None:
        """Apply a user's choice at once; the change, or None when the selection stays."""
        if source_id not in self._specs:
            raise KeyError(source_id)
        if mode not in MODES:
            raise ValueError(mode)
        self.modes[source_id] = mode
        if mode == AUTO:
            return None
        wanted = mode == ON
        if (source_id in self.selected) == wanted:
            return None
        self._apply(source_id, wanted)
        return SelectionChange(source_id, wanted, "user")

    def update(self, scorer: SourceScorer, now: float) -> list[SelectionChange]:
        """Re-decide the automatic sources from the scores at timeline time `now`.

        A source that failed to open is never selected; one that gives only digital silence is
        not kept as the fallback either (the UI would call a dead device "in use").
        """
        changes: list[SelectionChange] = []
        for kind in (Channel.MIC, Channel.SYSTEM):
            ids = [
                i
                for i, spec in self._specs.items()
                if spec.kind == kind and i not in self.unavailable
            ]
            wanted = {i for i in ids if self.modes[i] == ON}
            candidates = [i for i in ids if self.modes[i] == AUTO and self._wants(i, scorer, now)]
            candidates.sort(key=lambda i: scorer.score(i).active_seconds, reverse=True)
            for candidate in candidates:
                if all(
                    scorer.correlation(candidate, kept) < DUPLICATE_CORRELATION for kept in wanted
                ):
                    wanted.add(candidate)
            if not wanted:  # nothing speaks: keep what this kind had, if it is alive
                wanted = {
                    i
                    for i in ids
                    if i in self.selected and self.modes[i] != OFF and not scorer.score(i).silent
                }
            for i in [*ids, *(i for i in self.unavailable if self._specs[i].kind == kind)]:
                if (i in wanted) != (i in self.selected):
                    self._apply(i, i in wanted)
                    changes.append(SelectionChange(i, i in wanted, "auto"))
        return changes

    def _wants(self, source_id: str, scorer: SourceScorer, now: float) -> bool:
        score = scorer.score(source_id)
        if score.silent:
            return False
        if score.active_seconds >= ACTIVATE_SECONDS:
            return True
        last = scorer.last_active(source_id)
        return source_id in self.selected and last is not None and now - last <= HOLD_SECONDS

    def _apply(self, source_id: str, selected: bool) -> None:
        if selected:
            self.selected.add(source_id)
        else:
            self.selected.discard(source_id)


class SourceMixer:
    """Buffers, scores and mixes the sources; `step` returns the mixed blocks per channel."""

    def __init__(
        self,
        specs: Sequence[SourceSpec],
        rate: int,
        start_frame: int,
        selector: SourceSelector,
        scorer: SourceScorer | None = None,
        delay: float = MIX_DELAY_SECONDS,
        tolerance: float = 0.15,
    ) -> None:
        self._specs = list(specs)
        self._rate = rate
        self.selector = selector
        self.scorer = scorer or SourceScorer(rate)
        self._delay = round(delay * rate)
        self._latency = round(SCORE_LATENCY_SECONDS * rate)
        self._buffers = {
            spec.source_id: SourceBuffer(start_frame, round(tolerance * rate)) for spec in specs
        }
        self._score_cursor = start_frame
        self._mix_cursor = start_frame
        self._lock = threading.Lock()

    def push(self, source_id: str, samples: np.ndarray, at: float) -> None:
        with self._lock:
            self._buffers[source_id].push(samples, round(at * self._rate))

    def set_mode(self, source_id: str, mode: str) -> SelectionChange | None:
        with self._lock:
            return self.selector.set_mode(source_id, mode)

    def mark_unavailable(self, source_id: str) -> None:
        """The source failed to open: dropped from the selection at the next step."""
        with self._lock:
            self.selector.unavailable.add(source_id)

    def selected(self) -> set[str]:
        with self._lock:
            return set(self.selector.selected)

    def scores(self) -> dict[str, SourceScore]:
        with self._lock:
            return {spec.source_id: self.scorer.score(spec.source_id) for spec in self._specs}

    def step(
        self, now: float, final: bool = False
    ) -> tuple[dict[Channel, tuple[np.ndarray, float]], list[SelectionChange]]:
        """Score up to `now` (minus the capture latency), mix `delay` behind it.

        `final` scores and mixes everything pushed (at stop).
        """
        with self._lock:
            if final:
                head = max((b.end for b in self._buffers.values()), default=self._score_cursor)
            else:
                head = round(now * self._rate) - self._latency
            changes = self._score(head, final)
            target = head if final else head - self._delay
            return self._mix(target), changes

    def _score(self, head: int, final: bool) -> list[SelectionChange]:
        frame = self.scorer.frame
        whole = (head - self._score_cursor) // frame * frame
        if whole <= 0:
            return []
        end = self._score_cursor + whole
        frame_size = self.scorer.frame
        for source_id, buffer in self._buffers.items():
            if buffer.first is None:
                continue  # not open yet: no score (a device that opens late is not "silent")
            start = max(self._score_cursor, buffer.first)
            start = end - (end - start) // frame_size * frame_size  # whole frames ending at `end`
            if start < end:
                self.scorer.update(source_id, buffer.read(start, end), end / self._rate)
        self._score_cursor = end
        return self.selector.update(self.scorer, end / self._rate)

    def _mix(self, target: int) -> dict[Channel, tuple[np.ndarray, float]]:
        start = self._mix_cursor
        if target <= start:
            return {}
        out: dict[Channel, tuple[np.ndarray, float]] = {}
        for kind in (Channel.MIC, Channel.SYSTEM):
            ids = self.selector.of_kind(kind)
            blocks = [self._buffers[i].read(start, target) for i in ids]
            mixed = automix(blocks, self.scorer.frame) if blocks else None
            if mixed is None:
                mixed = np.zeros(target - start, np.float32)
            out[kind] = (mixed, start / self._rate)
        self._mix_cursor = target
        for buffer in self._buffers.values():
            buffer.drop_before(min(target, self._score_cursor))
        return out
