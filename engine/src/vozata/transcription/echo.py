"""Drop microphone segments that echo the system audio (phase 18, architecture §6).

Without headphones the microphone also hears the remote participants from the speakers, so their
words would appear twice (as `mic` and as `system`). `EchoFilter` sits in front of the sinks:
system segments pass through at once and are remembered for `SYSTEM_MEMORY_SECONDS`; each mic
segment is held for `hold_seconds` so the matching system segment can arrive, and is dropped when
enough of its words are found, in order, in the system words spoken at the same time.
"""

from __future__ import annotations

import difflib
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from vozata.domain import Channel, TranscriptSegment
from vozata.ports import TranscriptSink

SYSTEM_MEMORY_SECONDS = 30.0
_PUNCTUATION = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Lowercase, punctuation-free text with single spaces."""
    return " ".join(_PUNCTUATION.sub("", text.lower()).split())


def echo_score(mic: str, system: str) -> float:
    """Share of the mic words found, in order, in the system words (0 to 1).

    Asymmetric on purpose: an echo split across two system segments, or cut inside a longer one,
    still scores 1, while the user talking over the remote speaker adds unmatched mic words.
    """
    mic_words, system_words = normalize(mic).split(), normalize(system).split()
    if not mic_words or not system_words:
        return 0.0
    matcher = difflib.SequenceMatcher(None, mic_words, system_words, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(mic_words)


@dataclass(frozen=True)
class _Held:
    segment: TranscriptSegment
    deadline: float


class EchoFilter:
    """A `TranscriptSink` decorator that drops echoed mic segments before `downstream`.

    `clock` measures the hold (seconds, monotonic); `tick()` releases mic segments whose hold
    expired and must be called regularly by the thread that emits. `flush()` releases every held
    segment; `close()` flushes and closes `downstream`. `dropped` counts the dropped segments and
    `on_dropped` is told about each one. Not thread-safe: one thread emits, ticks and closes.
    """

    def __init__(
        self,
        downstream: TranscriptSink,
        similarity_threshold: float,
        hold_seconds: float,
        tolerance: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        on_dropped: Callable[[TranscriptSegment], None] = lambda segment: None,
    ) -> None:
        self._downstream = downstream
        self._threshold = similarity_threshold
        self._hold = hold_seconds
        self._tolerance = tolerance
        self._clock = clock
        self._on_dropped = on_dropped
        self._held: deque[_Held] = deque()
        self._system: deque[TranscriptSegment] = deque()
        self.dropped = 0

    def emit(self, segment: TranscriptSegment) -> None:
        self.tick()
        if segment.channel is Channel.MIC:
            if self._is_echo(segment):
                self._drop(segment)
            else:
                self._held.append(_Held(segment, self._clock() + self._hold))
            return
        self._remember(segment)
        self._downstream.emit(segment)
        for held in [held for held in self._held if self._is_echo(held.segment)]:
            self._held.remove(held)
            self._drop(held.segment)

    def tick(self) -> None:
        now = self._clock()
        while self._held and self._held[0].deadline <= now:
            self._downstream.emit(self._held.popleft().segment)

    def flush(self) -> None:
        while self._held:
            self._downstream.emit(self._held.popleft().segment)

    def close(self) -> None:
        self.flush()
        self._downstream.close()

    def _remember(self, segment: TranscriptSegment) -> None:
        self._system.append(segment)
        latest = max(kept.end for kept in self._system)
        while self._system[0].end < latest - SYSTEM_MEMORY_SECONDS:
            self._system.popleft()

    def _is_echo(self, mic: TranscriptSegment) -> bool:
        heard = self._system_text(mic.start - self._tolerance, mic.end + self._tolerance)
        return echo_score(mic.text, heard) >= self._threshold

    def _system_text(self, start: float, end: float) -> str:
        """System words spoken between `start` and `end` (whole segments without word times)."""
        parts: list[str] = []
        for segment in sorted(self._system, key=lambda kept: kept.start):
            if segment.words:
                parts.extend(w.text for w in segment.words if w.start <= end and w.end >= start)
            elif segment.start <= end and segment.end >= start:
                parts.append(segment.text)
        return " ".join(parts)

    def _drop(self, segment: TranscriptSegment) -> None:
        self.dropped += 1
        self._on_dropped(segment)
