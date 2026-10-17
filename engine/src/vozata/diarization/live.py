"""Live speaker labels: online clustering of speaker embeddings (phase 15, architecture §11)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace

import numpy as np

from vozata.domain import Channel, TranscriptSegment
from vozata.ports import SpeakerEmbedder

_log = logging.getLogger(__name__)


class LiveSpeakerTagger:
    """Tag system segments `system:<n>` while recording; best effort, never authoritative.

    Each segment's audio is embedded and compared (cosine similarity) with the running centroid
    (mean of the normalized embeddings) of every speaker so far: at or above `threshold` it joins
    the closest one, otherwise it starts a new speaker. Segments shorter than `min_seconds`,
    without audio or with an unusable embedding reuse the previous speaker (`system` before the
    first). Microphone segments are returned unchanged.

    An embedding slower than `max_seconds` (the window length: tagging could no longer keep up) or
    a failing embedder disables the tagger with a warning; from then on segments keep `system`.
    Not thread-safe: one thread tags.
    """

    def __init__(
        self,
        embedder: SpeakerEmbedder,
        threshold: float,
        min_seconds: float = 1.0,
        max_seconds: float = 5.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._embedder = embedder
        self._threshold = threshold
        self._min_seconds = min_seconds
        self._max_seconds = max_seconds
        self._clock = clock
        self._sums: list[np.ndarray] = []  # per speaker: sum of normalized embeddings
        self._previous: str | None = None
        self.disabled = False

    @property
    def speakers(self) -> int:
        return len(self._sums)

    def disable(self, reason: str) -> None:
        if not self.disabled:
            _log.warning("Live speaker identification disabled: %s", reason)
        self.disabled = True

    def tag(self, segment: TranscriptSegment, samples: np.ndarray) -> TranscriptSegment:
        if segment.channel is not Channel.SYSTEM or self.disabled:
            return segment
        speaker = self._previous
        if segment.end - segment.start >= self._min_seconds and len(samples):
            speaker = self._identify(samples) or speaker
        if speaker is None:
            return segment
        self._previous = speaker
        return replace(segment, speaker_id=speaker)

    def _identify(self, samples: np.ndarray) -> str | None:
        started = self._clock()
        try:
            vector = np.asarray(self._embedder.embed(samples), dtype=np.float64).ravel()
        except Exception as error:
            self.disable(f"the speaker embedder failed ({error})")
            return None
        elapsed = self._clock() - started
        _log.debug("Speaker embedding took %.3f s", elapsed)
        if elapsed > self._max_seconds:
            self.disable(f"embedding took {elapsed:.1f} s (limit {self._max_seconds:.1f} s)")
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm == 0.0:
            return None
        return self._assign(vector / norm)

    def _assign(self, unit: np.ndarray) -> str:
        best, best_similarity = -1, -1.0
        for index, total in enumerate(self._sums):
            similarity = float(unit @ total) / float(np.linalg.norm(total))
            if similarity > best_similarity:
                best, best_similarity = index, similarity
        if best >= 0 and best_similarity >= self._threshold:
            self._sums[best] = self._sums[best] + unit
        else:
            best = len(self._sums)
            self._sums.append(unit)
        return f"{Channel.SYSTEM.value}:{best + 1}"
