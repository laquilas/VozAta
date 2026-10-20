"""Transcribe the rest of a meeting from its stored audio (phase 40).

After Stop the live transcription ends without draining its backlog; this transcribes, from the
stored tracks, whatever the raw transcript does not cover yet (each channel from its
`ResumePoint`). The output matches the live transcript: the same chunkers, carry-over stitching,
rolling context, echo dedupe, segment ids and session-clock timestamps; it is appended to the raw
transcript. Live partials, live speakers, translation and observer events are not part of it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from vozata.audio.chunker import ChunkerFactory, fixed_windows
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.ports import AudioReader, SessionRepository, Transcriber, TranscriptSink
from vozata.processing.cancel import CancelToken
from vozata.transcription.context import RollingContext
from vozata.transcription.echo import EchoFilter
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.resume import ResumePoint, resume_points
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds

CHANNELS = (Channel.MIC, Channel.SYSTEM)
_INT16_SCALE = 32768.0


@dataclass(frozen=True)
class _Span:
    """The frames of one track still to transcribe: `start` (resume point) to `end`."""

    start: int
    end: int
    rate: int


class _ShiftedChunker:
    """A chunker whose own timeline starts at the resume point `offset` (so it does not pad the
    audio before it with silence); it is fed and emits session time."""

    def __init__(
        self,
        factory: ChunkerFactory,
        channel: Channel,
        offset: float,
        on_chunk: Callable[[AudioChunk], None],
    ) -> None:
        self._offset = offset
        self._chunker = factory(
            channel, lambda chunk: on_chunk(replace(chunk, start=chunk.start + offset))
        )

    def feed(self, samples: np.ndarray, at: float) -> None:
        self._chunker.feed(samples, at - self._offset)

    def flush(self) -> None:
        self._chunker.flush()


class OfflineTranscription:
    """Append the rest of a session's raw transcript from its stored audio, `block_seconds` of
    both channels at a time, in lockstep on the session timeline (echo dedupe compares mic and
    system of the same moment). Runs on the caller's thread; one instance per session job."""

    def __init__(
        self,
        settings: Settings,
        store: SessionRepository,
        audio: AudioReader,
        transcriber_factory: Callable[[], Transcriber],
        labeler: SpeakerLabeler,
        language: LanguageLock,
        hints: str | None,
        chunker_factory: ChunkerFactory | None,
        block_seconds: float = 10.0,
    ) -> None:
        self._settings = settings
        self._store = store
        self._audio = audio
        self._transcriber_factory = transcriber_factory
        self._labeler = labeler
        self._language = language
        self._hints = hints
        self._chunker_factory = chunker_factory or fixed_windows(settings)
        self._block_seconds = block_seconds
        self._now = 0.0  # session seconds of audio fed so far: the echo filter's clock

    def remaining_seconds(self, session_id: str) -> float:
        """Audio seconds not transcribed yet, summed over the channels (for job weights)."""
        points = resume_points(self._store.load_raw_transcript(session_id), CHANNELS)
        spans = self._spans(session_id, points)
        return sum((span.end - span.start) / span.rate for span in spans.values())

    def run(
        self, session_id: str, token: CancelToken, on_progress: Callable[[float], None]
    ) -> None:
        """Transcribe and append the rest; raises `StepCancelled` between blocks when `token` is
        cancelled (segments committed so far are kept; the carried tails are not flushed)."""
        token.raise_if_cancelled()
        existing = self._store.load_raw_transcript(session_id)
        points = resume_points(existing, CHANNELS)
        spans = self._spans(session_id, points)
        for span in spans.values():
            if span.rate != self._settings.sample_rate:
                raise ValueError(
                    f"Stored audio sample rate {span.rate} is not {self._settings.sample_rate}"
                )
        total = sum(span.end - span.start for span in spans.values())
        if total == 0:
            on_progress(1.0)
            return
        transcriber = self._transcriber_factory()
        try:
            sink = self._store.open_transcript(session_id, self._labeler)
            output, tick = self._output(sink, existing)
            try:
                stitchers = self._stitchers(transcriber, existing, points)
                chunkers = {
                    channel: _ShiftedChunker(
                        self._chunker_factory,
                        channel,
                        spans[channel].start / spans[channel].rate,
                        self._commit(stitchers[channel], output),
                    )
                    for channel in CHANNELS
                }
                self._feed(session_id, spans, chunkers, tick, token, on_progress, total)
                for channel in CHANNELS:
                    chunkers[channel].flush()
                    for segment in stitchers[channel].flush():
                        output.emit(segment)
            finally:
                output.close()
        finally:
            transcriber.close()

    def _spans(
        self, session_id: str, points: Mapping[Channel, ResumePoint]
    ) -> dict[Channel, _Span]:
        spans: dict[Channel, _Span] = {}
        for channel in CHANNELS:
            rate = self._audio.sample_rate(session_id, channel)
            end = self._audio.length(session_id, channel)
            spans[channel] = _Span(min(round(points[channel].start * rate), end), end, rate)
        return spans

    def _output(
        self, sink: TranscriptSink, existing: Sequence[TranscriptSegment]
    ) -> tuple[TranscriptSink, Callable[[], None]]:
        """Echo dedupe (when enabled) in front of `sink`, holding mic segments on audio time and
        knowing the system speech already written; also its `tick`."""
        self._now = 0.0
        if not self._settings.echo_dedupe_enabled:
            return sink, lambda: None
        echo = EchoFilter.from_settings(self._settings, sink, clock=lambda: self._now)
        for segment in existing:
            if segment.channel is Channel.SYSTEM:
                echo.remember(segment)
        return echo, echo.tick

    def _stitchers(
        self,
        transcriber: Transcriber,
        existing: Sequence[TranscriptSegment],
        points: Mapping[Channel, ResumePoint],
    ) -> dict[Channel, CarryOverStitcher]:
        """One stitcher per channel; ids continue and the context prompt knows the written text."""
        ids = SegmentIds({channel: point.next_index for channel, point in points.items()})
        stitchers: dict[Channel, CarryOverStitcher] = {}
        for channel in CHANNELS:
            context = RollingContext(self._settings.context_prompt_chars)
            context.language(self._language.current())
            for segment in sorted(existing, key=lambda written: written.end):
                if segment.channel is channel:
                    context.commit(segment.text, segment.end)
            stitchers[channel] = CarryOverStitcher(
                channel,
                transcriber,
                self._settings,
                self._language,
                ids.next,
                hints=self._hints,
                context=context,
            )
        return stitchers

    @staticmethod
    def _commit(
        stitcher: CarryOverStitcher, output: TranscriptSink
    ) -> Callable[[AudioChunk], None]:
        def on_chunk(chunk: AudioChunk) -> None:
            for segment in stitcher.on_chunk(chunk):
                output.emit(segment)

        return on_chunk

    def _feed(
        self,
        session_id: str,
        spans: Mapping[Channel, _Span],
        chunkers: Mapping[Channel, _ShiftedChunker],
        tick: Callable[[], None],
        token: CancelToken,
        on_progress: Callable[[float], None],
        total: int,
    ) -> None:
        """Feed block k of every channel before block k + 1 of any, each at its session time."""
        rate = self._settings.sample_rate
        block = max(1, round(self._block_seconds * rate))
        cursor = {channel: span.start for channel, span in spans.items()}
        timeline = min(span.start for span in spans.values() if span.start < span.end)
        fed = 0
        while any(cursor[channel] < spans[channel].end for channel in CHANNELS):
            token.raise_if_cancelled()
            timeline += block
            for channel in CHANNELS:
                stop = min(timeline, spans[channel].end)
                if cursor[channel] >= stop:
                    continue
                count = stop - cursor[channel]
                samples = self._audio.frames(session_id, channel, cursor[channel], count)
                self._now = max(self._now, stop / rate)
                chunkers[channel].feed(
                    samples.astype(np.float32) / _INT16_SCALE, cursor[channel] / rate
                )
                cursor[channel], fed = stop, fed + count
            tick()
            on_progress(fed / total)
