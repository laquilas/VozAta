"""Transcribe the rest of a meeting from its stored audio (phase 40).

After Stop the live transcription ends without draining its backlog; this transcribes, from the
stored tracks, whatever the raw transcript does not cover yet (each channel from its
`ResumePoint`, after the voiced tail the live stitcher dropped). The output matches the live
transcript: the same chunkers, carry-over stitching, rolling context, echo dedupe, segment ids and
session-clock timestamps; it is appended to the raw transcript. Live partials, live speakers,
translation and observer events are not part of it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence

from vozata.audio.chunker import ChunkerFactory, fixed_windows
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.output.sinks import CompositeSink
from vozata.ports import AudioReader, SessionRepository, Transcriber, TranscriptSink
from vozata.processing.cancel import CancelToken
from vozata.transcription.context import RollingContext
from vozata.transcription.echo import MATCH_TOLERANCE_SECONDS, EchoFilter
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline_feed import (
    CHANNELS,
    ShiftedChunker,
    Span,
    feed_in_lockstep,
    track_spans,
)
from vozata.transcription.resume import ResumePoint, resume_points
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds


class _Output:
    """The transcript sink behind echo dedupe (when enabled), whose holds run on audio time.

    The stored system segments are remembered as the timeline reaches them, so the filter's
    `SYSTEM_MEMORY_SECONDS` memory follows the audio being fed even when the mic resumes long
    before the system (live dropped every mic echo there, so none was written).
    """

    def __init__(
        self, settings: Settings, sink: TranscriptSink, existing: Sequence[TranscriptSegment]
    ) -> None:
        self._now = 0.0
        self._echo: EchoFilter | None = None
        self.sink = sink
        stored = [segment for segment in existing if segment.channel is Channel.SYSTEM]
        self._stored = deque(sorted(stored, key=lambda segment: segment.start))
        if settings.echo_dedupe_enabled:
            self._echo = EchoFilter.from_settings(settings, sink, clock=lambda: self._now)
            self.sink = self._echo

    def before_block(self, end: float) -> None:
        """Audio up to `end` (session seconds) is about to be fed."""
        self._now = end
        if self._echo is None:
            return
        while self._stored and self._stored[0].start <= end + MATCH_TOLERANCE_SECONDS:
            self._echo.remember(self._stored.popleft())

    def tick(self) -> None:
        if self._echo is not None:
            self._echo.tick()


class _Notify:
    def __init__(self, on_segment: Callable[[TranscriptSegment], None]) -> None:
        self.emit = on_segment

    def close(self) -> None:
        pass


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
        on_segment: Callable[[TranscriptSegment], None] | None = None,
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
        self._on_segment = on_segment  # also told every appended segment (CLI console)

    def remaining_seconds(self, session_id: str) -> float:
        """Audio seconds not transcribed yet, summed over the channels (for job weights)."""
        existing = self._store.load_raw_transcript(session_id)
        spans = self._spans(session_id, existing, resume_points(existing, CHANNELS))
        return sum((span.end - span.start) / span.rate for span in spans.values())

    def run(
        self, session_id: str, token: CancelToken, on_progress: Callable[[float], None]
    ) -> None:
        """Transcribe and append the rest; raises `StepCancelled` between blocks when `token` is
        cancelled (segments committed so far are kept; the carried tails are not flushed)."""
        token.raise_if_cancelled()
        existing = sorted(self._store.load_raw_transcript(session_id), key=lambda s: s.end)
        points = resume_points(existing, CHANNELS)
        spans = self._spans(session_id, existing, points)
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
            sink: TranscriptSink = self._store.open_transcript(session_id, self._labeler)
            if self._on_segment is not None:
                sink = CompositeSink([sink, _Notify(self._on_segment)])
            output = _Output(self._settings, sink, existing)
            try:
                stitchers = self._stitchers(transcriber, existing, points)
                chunkers = {
                    channel: ShiftedChunker(
                        self._chunker_factory,
                        channel,
                        spans[channel].start / spans[channel].rate,
                        self._commit(stitchers[channel], output.sink),
                    )
                    for channel in CHANNELS
                }

                def after_block(fraction: float) -> None:
                    output.tick()
                    on_progress(fraction)

                feed_in_lockstep(
                    self._audio,
                    session_id,
                    spans,
                    chunkers,
                    self._block_seconds,
                    token,
                    output.before_block,
                    after_block,
                )
                for channel in CHANNELS:
                    chunkers[channel].flush()
                    for segment in stitchers[channel].flush():
                        output.sink.emit(segment)
            finally:
                output.sink.close()
        finally:
            transcriber.close()

    def _spans(
        self,
        session_id: str,
        existing: Sequence[TranscriptSegment],
        points: Mapping[Channel, ResumePoint],
    ) -> dict[Channel, Span]:
        written = {segment.channel for segment in existing}
        threshold = self._settings.silence_rms_threshold
        return track_spans(self._audio, session_id, points, written, threshold)

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
            for segment in existing:  # sorted by end
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
