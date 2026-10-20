"""Read a meeting's stored tracks from their resume points and feed them to chunkers in lockstep.

Block k of every channel is fed before block k + 1 of any, each at its session time, so echo
dedupe sees the mic and the system audio of the same moment together (phase 40).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace

import numpy as np

from vozata.audio.chunker import ChunkerFactory
from vozata.domain import AudioChunk, Channel
from vozata.ports import AudioReader
from vozata.processing.cancel import CancelToken
from vozata.transcription.resume import ResumePoint
from vozata.transcription.stitcher import MAX_WORD_TAIL_SECONDS, voiced_end

CHANNELS = (Channel.MIC, Channel.SYSTEM)
_INT16_SCALE = 32768.0


@dataclass(frozen=True)
class Span:
    """The frames of one track still to transcribe: `start` (resume point) to `end`."""

    start: int
    end: int
    rate: int


def track_spans(
    audio: AudioReader,
    session_id: str,
    points: Mapping[Channel, ResumePoint],
    written: Collection[Channel],
    silence_threshold: float,
) -> dict[Channel, Span]:
    """Each channel's frames still to transcribe.

    A channel with written segments starts after the voiced tail (at most
    `MAX_WORD_TAIL_SECONDS`) of its last segment's `end`, where the live stitcher cut and dropped
    the audio, so no word fragment is transcribed twice.
    """
    spans: dict[Channel, Span] = {}
    for channel in CHANNELS:
        rate = audio.sample_rate(session_id, channel)
        end = audio.length(session_id, channel)
        start = min(round(points[channel].start * rate), end)
        if channel in written and start < end:
            probe = audio.frames(
                session_id, channel, start, round(MAX_WORD_TAIL_SECONDS * rate) + 1
            )
            tail = voiced_end(probe.astype(np.float32) / _INT16_SCALE, 0.0, rate, silence_threshold)
            start = min(start + round(tail * rate), end)
        spans[channel] = Span(start, end, rate)
    return spans


class ShiftedChunker:
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


def feed_in_lockstep(
    audio: AudioReader,
    session_id: str,
    spans: Mapping[Channel, Span],
    chunkers: Mapping[Channel, ShiftedChunker],
    block_seconds: float,
    token: CancelToken,
    before_block: Callable[[float], None],
    after_block: Callable[[float], None],
) -> None:
    """Feed every span (one rate, at least one not empty) in `block_seconds` steps of one shared
    timeline.

    Each step checks `token` (raises `StepCancelled`), calls `before_block(end)` with the step's
    end in session seconds, feeds each channel's part of the step (a channel joins once the
    timeline reaches its resume point), then calls `after_block(fraction)` with the share of all
    frames fed so far (0..1).
    """
    total = sum(span.end - span.start for span in spans.values())
    rate = next(iter(spans.values())).rate
    block = max(1, round(block_seconds * rate))
    cursor = {channel: span.start for channel, span in spans.items()}
    timeline = min(span.start for span in spans.values() if span.start < span.end)
    fed = 0
    while any(cursor[channel] < spans[channel].end for channel in spans):
        token.raise_if_cancelled()
        timeline += block
        before_block(timeline / rate)
        for channel in CHANNELS:
            stop = min(timeline, spans[channel].end)
            if cursor[channel] >= stop:
                continue
            count = stop - cursor[channel]
            samples = audio.frames(session_id, channel, cursor[channel], count)
            chunkers[channel].feed(
                samples.astype(np.float32) / _INT16_SCALE, cursor[channel] / rate
            )
            cursor[channel], fed = stop, fed + count
        after_block(fed / total)
