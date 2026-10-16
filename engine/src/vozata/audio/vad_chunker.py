"""Cut a channel's audio into transcription chunks at the pauses between phrases (phase 27)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from vozata.domain import AudioChunk, Channel
from vozata.ports import SpeechDetector

IDLE_KEEP_SECONDS = 1.0  # audio kept while nobody speaks, so a starting word is never clipped

Span = tuple[float, float]


class VadChunker:
    """Same interface as `FixedWindowChunker`; chunks end in the middle of a pause.

    Every `check_seconds` the buffer since the last cut goes to the `SpeechDetector`. Spans closer
    than `min_silence` belong to one phrase. A phrase is cut once `min_silence` of pause follows
    it; speech shorter than `min_chunk` (a blip) waits for the next phrase. At `max_chunk` the
    buffer is forced out at its longest pause, or whole. Leading silence is dropped down to
    `speech_pad`, so `AudioChunk.start` stays in session time. A chunk is `complete` when it ends in
    a pause of at least `min_silence`: the stitcher then commits all of it.
    """

    def __init__(
        self,
        channel: Channel,
        sample_rate: int,
        on_chunk: Callable[[AudioChunk], None],
        detector: SpeechDetector,
        *,
        min_silence: float,
        min_chunk: float,
        max_chunk: float,
        speech_pad: float,
        check_seconds: float = 0.25,
        tolerance: float = 0.15,
    ) -> None:
        self._channel = channel
        self._rate = sample_rate
        self._on_chunk = on_chunk
        self._detector = detector
        self._min_silence = min_silence
        self._min_chunk = min_chunk
        self._max_chunk = max_chunk
        self._pad = speech_pad
        self._tail = max(speech_pad, min_silence / 2)  # longest pause kept after a phrase
        self._check = round(check_seconds * sample_rate)
        self._tolerance = round(tolerance * sample_rate)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._blocks: list[np.ndarray] = []
        self._position = 0  # session sample index just after the last accepted sample
        self._unchecked = 0
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        if value and not self._paused:
            self.flush()
        self._paused = value

    def feed(self, samples: np.ndarray, at: float) -> None:
        """Accept a block whose first sample belongs at session time `at`."""
        start = round(at * self._rate)
        if self._paused:
            self._position = max(self._position, start + len(samples))
            return
        gap = start - self._position
        if gap > self._tolerance:
            self._append(np.zeros(gap, dtype=np.float32))
        self._append(samples)
        if self._unchecked >= self._check:
            self._unchecked = 0
            while self._cut():
                pass

    def buffered(self) -> AudioChunk | None:
        """A copy of the audio not cut yet (for interim text), or None."""
        audio = self._audio()
        if not len(audio):
            return None
        start = (self._position - len(audio)) / self._rate
        return AudioChunk(self._channel, start, audio.copy())

    def flush(self) -> None:
        """Emit the buffered speech, if any, as a complete chunk; drop pure silence."""
        audio = self._audio()
        spans = self._detector.speech_spans(audio) if len(audio) else []
        if spans:
            self._drop(self._samples(spans[0][0] - self._pad))
            self._emit(len(self._buffer), complete=True)
        self._buffer = np.zeros(0, dtype=np.float32)

    def _cut(self) -> bool:
        """Emit at most one chunk from the buffer; True when one was emitted."""
        audio = self._audio()
        raw = self._detector.speech_spans(audio)
        duration = len(audio) / self._rate
        if not raw:
            self._drop(len(audio) - round(IDLE_KEEP_SECONDS * self._rate))
            return False
        lead = max(0.0, raw[0][0] - self._pad)
        if lead > 0:
            self._drop(self._samples(lead))
            raw = [(start - lead, end - lead) for start, end in raw]
            duration -= lead
        phrases = _merge(raw, self._min_silence)
        for i, (_, end) in enumerate(phrases):
            pause = (phrases[i + 1][0] if i + 1 < len(phrases) else duration) - end
            if pause >= self._min_silence and end - phrases[0][0] >= self._min_chunk:
                self._emit(self._samples(end + min(pause / 2, self._tail)), complete=True)
                return True
        if duration >= self._max_chunk:
            end, pause = _longest_pause(raw, duration)
            cut = end + min(pause / 2, self._tail) if pause > 0 else duration
            self._emit(self._samples(cut), complete=pause >= self._min_silence)
            return True
        return False

    def _append(self, samples: np.ndarray) -> None:
        self._blocks.append(samples.astype(np.float32, copy=False))
        self._position += len(samples)
        self._unchecked += len(samples)

    def _audio(self) -> np.ndarray:
        if self._blocks:
            self._buffer = np.concatenate((self._buffer, *self._blocks))
            self._blocks = []
        return self._buffer

    def _drop(self, count: int) -> None:
        if count > 0:
            self._buffer = self._buffer[count:]

    def _emit(self, count: int, *, complete: bool) -> None:
        start = (self._position - len(self._buffer)) / self._rate
        samples = self._buffer[:count]
        self._buffer = self._buffer[count:]
        self._on_chunk(AudioChunk(self._channel, start, samples, complete=complete))

    def _samples(self, seconds: float) -> int:
        return round(seconds * self._rate)


def _merge(spans: Sequence[Span], min_silence: float) -> list[Span]:
    """Join spans separated by less than `min_silence` into phrases."""
    phrases = [spans[0]]
    for start, end in spans[1:]:
        if start - phrases[-1][1] < min_silence:
            phrases[-1] = (phrases[-1][0], end)
        else:
            phrases.append((start, end))
    return phrases


def _longest_pause(spans: Sequence[Span], duration: float) -> tuple[float, float]:
    """(end of the speech before it, length) of the longest pause after any span."""
    pauses = [
        (end, (spans[i + 1][0] if i + 1 < len(spans) else duration) - end)
        for i, (_, end) in enumerate(spans)
    ]
    return max(pauses, key=lambda pause: pause[1])
