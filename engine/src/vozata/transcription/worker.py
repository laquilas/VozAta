"""The single transcription thread: one GPU, every channel (architecture §6)."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Mapping
from typing import Protocol

from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.ports import TranscriptSink

_log = logging.getLogger(__name__)


class ChunkStitcher(Protocol):
    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]: ...

    def flush(self) -> list[TranscriptSegment]: ...


class TranscriptionWorker:
    """Consume `AudioChunk`s, route them to their channel's stitcher and emit segments.

    The transcriber is only ever called from this thread. A failing chunk is logged and skipped.
    `stop()` drains the queue, then flushes every stitcher; the sink is closed by its owner.
    """

    def __init__(
        self,
        chunks: queue.Queue[AudioChunk],
        stitchers: Mapping[Channel, ChunkStitcher],
        sink: TranscriptSink,
        backlog_per_channel: int = 3,
    ) -> None:
        self._chunks = chunks
        self._stitchers = stitchers
        self._sink = sink
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
            self._finish()
        else:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._process(self._chunks.get(timeout=0.05))
            except queue.Empty:
                continue
        self._finish()

    def _finish(self) -> None:
        while True:
            try:
                self._process(self._chunks.get_nowait())
            except queue.Empty:
                break
        for channel, stitcher in self._stitchers.items():
            try:
                self._emit(stitcher.flush())
            except Exception:
                _log.exception("Flushing the %s transcription failed", channel)

    def _process(self, chunk: AudioChunk) -> None:
        self._check_backlog()
        try:
            segments = self._stitchers[chunk.channel].on_chunk(chunk)
        except Exception:
            _log.exception("Transcribing %s at %.1f s failed", chunk.channel, chunk.start)
            return
        self._emit(segments)

    def _emit(self, segments: list[TranscriptSegment]) -> None:
        for segment in segments:
            self._sink.emit(segment)

    def _check_backlog(self) -> None:
        backlog = self._chunks.qsize()
        if backlog > self._backlog_limit and not self._behind:
            _log.warning("Transcription is slower than real time: %d chunks waiting", backlog)
        self._behind = backlog > self._backlog_limit
