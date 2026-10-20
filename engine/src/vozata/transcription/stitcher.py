"""Carry-over stitching of fixed windows into whole phrases (architecture §7).

Fixed windows cut words and sentences. The unfinished tail of each window is carried into the next
one and transcribed again; committed audio is dropped, so no text is duplicated. A `complete` chunk
(cut in a pause by the VAD chunker) is committed whole.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

import numpy as np

from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptSegment, Word
from vozata.ports import Transcriber
from vozata.transcription.context import RollingContext

_SENTENCE_END = (".", "?", "!", "…")
MAX_WORD_TAIL_SECONDS = 0.3  # Whisper word ends run early; voiced audio may continue this long
MIN_PARTIAL_SPEECH_SECONDS = 1.0  # interim text needs this much voiced audio
_FRAME_SECONDS = 0.01


class LanguageProvider(Protocol):
    def current(self) -> str | None: ...

    def observe(self, language: str | None, speech_seconds: float) -> None: ...


class SegmentIds:
    """Session-wide segment ids: `<channel>-<6-digit counter>`, counted per channel.

    `start` gives a channel's next number (resuming a transcript); other channels start at 1.
    """

    def __init__(self, start: Mapping[Channel, int] | None = None) -> None:
        self._counts: Counter[Channel] = Counter(
            {channel: number - 1 for channel, number in (start or {}).items()}
        )

    def next(self, channel: Channel) -> str:
        self._counts[channel] += 1
        return f"{channel.value}-{self._counts[channel]:06d}"


class CarryOverStitcher:
    """Turn one channel's windows into transcript segments ending at phrase boundaries.

    `hints` (vocabulary, phase 19) go with every transcription; `context` (the channel's rolling
    context prompt, O4) gives each transcription the recent committed text and learns every
    committed segment.
    """

    def __init__(
        self,
        channel: Channel,
        transcriber: Transcriber,
        settings: Settings,
        language_provider: LanguageProvider,
        id_factory: Callable[[Channel], str],
        hints: str | None = None,
        context: RollingContext | None = None,
    ) -> None:
        self._channel = channel
        self._transcriber = transcriber
        self._settings = settings
        self._language = language_provider
        self._next_id = id_factory
        self._hints = hints
        self._context = context or RollingContext(0)
        self._pending = np.zeros(0, dtype=np.float32)
        self._pending_start = 0.0

    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        has_pending = len(self._pending) > 0
        audio = np.concatenate((self._pending, chunk.samples)) if has_pending else chunk.samples
        audio_start = self._pending_start if has_pending else chunk.start
        if not has_pending and _rms(audio) < self._settings.silence_rms_threshold:
            return []
        words = self._transcribe(audio, audio_start)
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

    def partial(self, tail: AudioChunk | None) -> tuple[float, str] | None:
        """Interim text of the carried audio plus `tail` (audio not chunked yet); commits nothing.

        None without at least `MIN_PARTIAL_SPEECH_SECONDS` of voiced audio or without words. The
        language lock is not fed: only committed text decides the conversation language.
        """
        parts = [self._pending] if len(self._pending) else []
        if tail is not None:
            parts.append(tail.samples)
        if not parts:
            return None
        audio = np.concatenate(parts)
        if self._voiced_seconds(audio) < MIN_PARTIAL_SPEECH_SECONDS:
            return None
        start = self._pending_start if len(self._pending) else tail.start  # type: ignore[union-attr]
        language = self._language.current()
        self._context.language(language)
        prompt = self._context.prompt()
        result = self._transcriber.transcribe(audio, language, self._hints, prompt)
        text = "".join(word.text for word in result.words).strip()
        return (start, text) if text else None

    def flush(self) -> list[TranscriptSegment]:
        """Transcribe the carried audio, if any, and commit every word."""
        if len(self._pending) == 0:
            return []
        audio, audio_start = self._pending, self._pending_start
        self._clear()
        words = self._transcribe(audio, audio_start)
        return [self._segment(words, audio_start)] if words else []

    def _transcribe(self, audio: np.ndarray, at: float) -> tuple[Word, ...]:
        language = self._language.current()
        self._context.language(language)
        prompt = self._context.take(at)
        result = self._transcriber.transcribe(audio, language, self._hints, prompt)
        self._context.observe(result.avg_logprob)
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

    def _voiced_seconds(self, audio: np.ndarray) -> float:
        frame = round(_FRAME_SECONDS * self._settings.sample_rate)
        frames = audio[: len(audio) // frame * frame].reshape(-1, frame).astype(np.float64)
        rms = np.sqrt(np.mean(np.square(frames), axis=1))
        return float(np.count_nonzero(rms >= self._settings.silence_rms_threshold)) * _FRAME_SECONDS

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
        segment = TranscriptSegment(
            segment_id=self._next_id(self._channel),
            channel=self._channel,
            speaker_id=self._channel.value,
            start=absolute[0].start,
            end=absolute[-1].end,
            text="".join(word.text for word in words).strip(),
            words=absolute,
        )
        self._context.commit(segment.text, segment.end)
        return segment

    def _clear(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)
        self._pending_start = 0.0


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0.0
