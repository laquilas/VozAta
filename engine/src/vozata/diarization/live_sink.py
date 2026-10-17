"""The live speaker worker: tags system segments on its own thread (phase 15, architecture §6)."""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable

import numpy as np

from vozata.diarization.live import LiveSpeakerTagger
from vozata.domain import AudioChunk, TranscriptSegment
from vozata.ports import TranscriptSink

_log = logging.getLogger(__name__)
_CLOSE = object()


class AudioHistory:
    """The last `keep_seconds` of one channel's chunks, to cut a segment's clip (thread-safe)."""

    def __init__(self, sample_rate: int, keep_seconds: float = 60.0) -> None:
        self._rate = sample_rate
        self._keep = keep_seconds
        self._chunks: deque[AudioChunk] = deque()
        self._lock = threading.Lock()

    def add(self, chunk: AudioChunk) -> None:
        with self._lock:
            self._chunks.append(chunk)
            latest = chunk.start + len(chunk.samples) / self._rate
            while self._chunks and self._end(self._chunks[0]) < latest - self._keep:
                self._chunks.popleft()

    def clip(self, start: float, end: float) -> np.ndarray:
        """The samples between `start` and `end` (session seconds) still kept; may be empty."""
        with self._lock:
            chunks = sorted(self._chunks, key=lambda chunk: chunk.start)
        parts: list[np.ndarray] = []
        covered = start
        for chunk in chunks:
            first = max(covered, chunk.start)
            last = min(end, self._end(chunk))
            if last <= first:
                continue
            offset = round((first - chunk.start) * self._rate)
            parts.append(chunk.samples[offset : offset + round((last - first) * self._rate)])
            covered = last
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def _end(self, chunk: AudioChunk) -> float:
        return chunk.start + len(chunk.samples) / self._rate


class LiveSpeakerSink:
    """A `TranscriptSink` that forwards every segment, in order, to `downstream` on its own thread.

    System segments get a live `system:<n>` speaker from the tagger, using their clip from
    `audio`; `emit` only enqueues, so the transcription thread never waits for an embedding.
    The tagger is built by `load` on a separate thread (the model takes a while to load);
    segments forwarded before it is ready, or after it failed or disabled itself, keep `system`.
    A failed load calls `on_failed`. `close()` forwards what is queued, closes `downstream` and
    releases the embedder (once loaded, if it was still loading).
    """

    def __init__(
        self,
        downstream: TranscriptSink,
        load: Callable[[], LiveSpeakerTagger],
        audio: AudioHistory,
        on_failed: Callable[[Exception], None] = lambda error: None,
    ) -> None:
        self._downstream = downstream
        self._load = load
        self._audio = audio
        self._on_failed = on_failed
        self._queue: queue.Queue[object] = queue.Queue()
        self._lock = threading.Lock()
        self._tagger: LiveSpeakerTagger | None = None
        self._closed = False
        self._loader = threading.Thread(target=self._load_tagger, name="live-speakers-load")
        self._thread = threading.Thread(target=self._run, name="live-speakers")
        self._started = False

    def start(self) -> None:
        self._started = True
        self._loader.start()
        self._thread.start()

    def emit(self, segment: TranscriptSegment) -> None:
        self._queue.put(segment)

    def close(self) -> None:
        self._queue.put(_CLOSE)
        if self._started:
            self._thread.join()
        else:
            self._run()
        self._downstream.close()
        with self._lock:
            self._closed = True
            tagger, self._tagger = self._tagger, None
        if tagger is not None:
            tagger.close()

    def _load_tagger(self) -> None:
        try:
            tagger = self._load()
        except Exception as error:
            _log.warning("Live speaker identification is off: %s", error)
            self._on_failed(error)
            return
        with self._lock:
            if not self._closed:
                self._tagger = tagger
                return
        tagger.close()  # the session stopped while the model was loading

    def _run(self) -> None:
        while (item := self._queue.get()) is not _CLOSE:
            assert isinstance(item, TranscriptSegment)
            self._forward(item)

    def _forward(self, segment: TranscriptSegment) -> None:
        with self._lock:
            tagger = self._tagger
        if tagger is not None:
            try:
                segment = tagger.tag(segment, self._audio.clip(segment.start, segment.end))
            except Exception:
                _log.exception("Live speaker tagging of %s failed", segment.segment_id)
        try:
            self._downstream.emit(segment)
        except Exception:
            _log.exception("Writing segment %s failed", segment.segment_id)
