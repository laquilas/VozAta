"""Carry-over stitching of fixed windows into whole phrases (architecture §7).

Fixed windows cut words and sentences. The unfinished tail of each window is carried into the next
one and transcribed again; committed audio is dropped, so no text is duplicated. A `complete` chunk
(cut in a pause by the VAD chunker) is committed whole.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np

from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptSegment, Word
from vozata.ports import Transcriber

_SENTENCE_END = (".", "?", "!", "…")
MAX_WORD_TAIL_SECONDS = 0.3  # Whisper word ends run early; voiced audio may continue this long
_FRAME_SECONDS = 0.01


class LanguageProvider(Protocol):
    def current(self) -> str | None: ...

    def observe(self, language: str | None, speech_seconds: float) -> None: ...


class SegmentIds:
    """Session-wide segment ids: `<channel>-<6-digit counter>`, counted per channel."""

    def __init__(self) -> None:
        self._counts: Counter[Channel] = Counter()

    def next(self, channel: Channel) -> str:
        self._counts[channel] += 1
        return f"{channel.value}-{self._counts[channel]:06d}"


class CarryOverStitcher:
    """Turn one channel's windows into transcript segments ending at phrase boundaries."""

    def __init__(
        self,
        channel: Channel,
        transcriber: Transcriber,
        settings: Settings,
        language_provider: LanguageProvider,
        id_factory: Callable[[Channel], str],
        hints: str | None = None,
    ) -> None:
        self._channel = channel
        self._transcriber = transcriber
        self._settings = settings
        self._language = language_provider
        self._next_id = id_factory
        self._hints = hints
        self._pending = np.zeros(0, dtype=np.float32)
        self._pending_start = 0.0

    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        has_pending = len(self._pending) > 0
        audio = np.concatenate((self._pending, chunk.samples)) if has_pending else chunk.samples
        audio_start = self._pending_start if has_pending else chunk.start
        if not has_pending and _rms(audio) < self._settings.silence_rms_threshold:
            return []
        words = self._transcribe(audio)
        if not words:
            self._clear()
            return []
        if chunk.complete:
            self._clear()
            return [self._segment(words, audio_start)]
        duration = len(audio) / self._settings.sample_rate
        cut = self._cut_index(words, duration)
        if cut is None:
            self._pending, self._pending_start = audio, audio_start
            return []
        cut_word = words[cut]
        next_word = words[cut + 1] if cut + 1 < len(words) else None
        if next_word is not None:
            cut_time = (cut_word.end + next_word.start) / 2
        else:
            cut_time = self._voiced_end(audio, cut_word.end, duration)
        self._pending = audio[round(cut_time * self._settings.sample_rate) :]
        self._pending_start = audio_start + cut_time
        return [self._segment(words[: cut + 1], audio_start)]

    def flush(self) -> list[TranscriptSegment]:
        """Transcribe the carried audio, if any, and commit every word."""
        if len(self._pending) == 0:
            return []
        audio, audio_start = self._pending, self._pending_start
        self._clear()
        words = self._transcribe(audio)
        return [self._segment(words, audio_start)] if words else []

    def _transcribe(self, audio: np.ndarray) -> tuple[Word, ...]:
        result = self._transcriber.transcribe(audio, self._language.current(), self._hints)
        if result.words:
            speech = sum(word.end - word.start for word in result.words)
            self._language.observe(result.language, speech)
        return result.words

    def _cut_index(self, words: Sequence[Word], duration: float) -> int | None:
        limit = duration - self._settings.tail_margin_seconds
        safe = [i for i, word in enumerate(words) if word.end <= limit]
        for i in reversed(safe):
            if words[i].text.strip().endswith(_SENTENCE_END):
                return i
        gap = self._settings.pause_gap_seconds
        for i in reversed(safe):
            if i + 1 < len(words) and words[i + 1].start - words[i].end >= gap:
                return i
        if duration >= self._settings.max_carry_seconds:
            return len(words) - 1
        return None

    def _voiced_end(self, audio: np.ndarray, start: float, duration: float) -> float:
        """Extend `start` through still-voiced 10 ms frames, at most `MAX_WORD_TAIL_SECONDS`."""
        rate = self._settings.sample_rate
        frame = round(_FRAME_SECONDS * rate)
        end = start
        limit = min(duration, start + MAX_WORD_TAIL_SECONDS)
        while end + _FRAME_SECONDS <= limit + 1e-9:
            first = round(end * rate)
            if _rms(audio[first : first + frame]) < self._settings.silence_rms_threshold:
                break
            end += _FRAME_SECONDS
        return end

    def _segment(self, words: Sequence[Word], offset: float) -> TranscriptSegment:
        absolute = tuple(
            Word(word.text.strip(), offset + word.start, offset + word.end, word.probability)
            for word in words
        )
        return TranscriptSegment(
            segment_id=self._next_id(self._channel),
            channel=self._channel,
            speaker_id=self._channel.value,
            start=absolute[0].start,
            end=absolute[-1].end,
            text="".join(word.text for word in words).strip(),
            words=absolute,
        )

    def _clear(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)
        self._pending_start = 0.0


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0.0
