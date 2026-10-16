"""The single transcription thread: one GPU, every channel (architecture §6)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.ports import TranscriptSink

_log = logging.getLogger(__name__)


class ChunkStitcher(Protocol):
    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]: ...

    def flush(self) -> list[TranscriptSegment]: ...

    def partial(self, tail: AudioChunk | None) -> tuple[float, str] | None: ...


@dataclass(frozen=True)
class PartialOptions:
    """Interim text (phase 28): `snapshot(channel)` is the audio not chunked yet; `emit` sends
    `(channel, start, text)`, an empty text clearing the channel's line."""

    interval: float
    snapshot: Callable[[Channel], AudioChunk | None]
    emit: Callable[[Channel, float, str], None]
    clock: Callable[[], float] = field(default=time.monotonic)


class TranscriptionWorker:
    """Consume `AudioChunk`s, route them to their channel's stitcher and emit segments.

    The transcriber is only ever called from this thread. A failing chunk is logged and skipped.
    `stop()` drains the queue, then flushes every stitcher; the sink is closed by its owner.

    `load` (optional) runs first on this thread, e.g. to load the speech model while capture is
    already running; chunks wait in the queue meanwhile. When it returns False every chunk is
    dropped and nothing is flushed. A worker that was never started never loads.

    With `partials`, an idle worker (empty queue) previews each channel's uncommitted audio at
    most once per `interval` and sends the text when it changed. A shown partial is cleared when
    its channel's next chunk commits nothing, and at stop; a committed segment replaces it.
    """

    def __init__(
        self,
        chunks: queue.Queue[AudioChunk],
        stitchers: Mapping[Channel, ChunkStitcher],
        sink: TranscriptSink,
        backlog_per_channel: int = 3,
        load: Callable[[], bool] | None = None,
        partials: PartialOptions | None = None,
    ) -> None:
        self._chunks = chunks
        self._load = load
        self._usable = True
        self._stitchers = stitchers
        self._sink = sink
        self._partials = partials
        self._previewed_at: dict[Channel, float] = {}
        self._shown: dict[Channel, str] = {}
        self._backlog_limit = backlog_per_channel * len(stitchers)
        self._behind = False
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="transcription")
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is None:
            self._usable = self._load is None
            self._finish()
        else:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        if self._load is not None:
            self._usable = self._load()
            self._behind = True  # catching up on audio queued while loading is not "slow"
        while not self._stopping.is_set():
            try:
                self._process(self._chunks.get(timeout=0.05))
            except queue.Empty:
                self._preview()
        self._finish()

    def _finish(self) -> None:
        while True:
            try:
                self._process(self._chunks.get_nowait())
            except queue.Empty:
                break
        if not self._usable:
            return
        for channel, stitcher in self._stitchers.items():
            try:
                self._emit(stitcher.flush())
            except Exception:
                _log.exception("Flushing the %s transcription failed", channel)
        for channel in list(self._shown):
            self._clear(channel, 0.0)

    def _process(self, chunk: AudioChunk) -> None:
        if not self._usable:
            return
        self._check_backlog()
        try:
            segments = self._stitchers[chunk.channel].on_chunk(chunk)
        except Exception:
            _log.exception("Transcribing %s at %.1f s failed", chunk.channel, chunk.start)
            return
        self._emit(segments)
        if segments:
            self._shown.pop(chunk.channel, None)  # the segment replaces the partial
        elif chunk.channel in self._shown:
            self._clear(chunk.channel, chunk.start)

    def _preview(self) -> None:
        options = self._partials
        if options is None or not self._usable:
            return
        for channel, stitcher in self._stitchers.items():
            if not self._chunks.empty():
                return  # committed work first
            now = options.clock()
            if now - self._previewed_at.get(channel, float("-inf")) < options.interval:
                continue
            self._previewed_at[channel] = now
            try:
                preview = stitcher.partial(options.snapshot(channel))
            except Exception:
                _log.exception("Interim text for %s failed", channel)
                continue
            if preview is not None and preview[1] != self._shown.get(channel):
                self._shown[channel] = preview[1]
                options.emit(channel, *preview)

    def _clear(self, channel: Channel, start: float) -> None:
        del self._shown[channel]
        assert self._partials is not None  # only partials are ever shown
        self._partials.emit(channel, start, "")

    def _emit(self, segments: list[TranscriptSegment]) -> None:
        for segment in segments:
            self._sink.emit(segment)

    def _check_backlog(self) -> None:
        backlog = self._chunks.qsize()
        if backlog > self._backlog_limit and not self._behind:
            _log.warning("Transcription is slower than real time: %d chunks waiting", backlog)
        self._behind = backlog > self._backlog_limit
