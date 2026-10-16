"""The live part of a session: WAV writers, chunkers, the transcription worker and sinks."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable

import numpy as np

from vozata.audio.chunker import FixedWindowChunker
from vozata.audio.levels import rms_db
from vozata.audio.wav_writer import AlignedWavWriter
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.output.sinks import CompositeSink, JsonlSink, MarkdownSink
from vozata.ports import SessionObserver, Transcriber
from vozata.storage.session_store import SessionPaths
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds
from vozata.transcription.worker import TranscriptionWorker


class _ObserverSink:
    def __init__(self, observer: SessionObserver) -> None:
        self._observer = observer

    def emit(self, segment: TranscriptSegment) -> None:
        self._observer.on_segment(segment)

    def close(self) -> None:
        pass


class _Track:
    """One channel's writer and chunker; the lock serializes capture writes and pause toggles."""

    def __init__(self, writer: AlignedWavWriter, chunker: FixedWindowChunker) -> None:
        self.writer = writer
        self.chunker = chunker
        self.lock = threading.Lock()


class CapturePipeline:
    """Route captured samples to WAVs and transcription; segments go to files and the observer.

    `receiver(channel)` is the callback for that channel's source. Samples arriving after
    `stop_capture()` (or before `accept()`) are ignored.
    """

    def __init__(
        self,
        channels: Iterable[Channel],
        paths: SessionPaths,
        settings: Settings,
        transcriber: Transcriber,
        language: LanguageLock,
        labeler: SpeakerLabeler,
        observer: SessionObserver,
    ) -> None:
        self._rate = settings.sample_rate
        self._observer = observer
        self._accepting = False
        chunks: queue.Queue[AudioChunk] = queue.Queue()
        self._tracks = {
            channel: _Track(
                AlignedWavWriter(paths.wav(channel), self._rate),
                FixedWindowChunker(channel, settings.chunk_seconds, self._rate, chunks.put),
            )
            for channel in channels
        }
        self._sink = CompositeSink(
            [
                JsonlSink(paths.transcript_jsonl),
                MarkdownSink(paths.transcript_md, labeler),
                _ObserverSink(observer),
            ]
        )
        ids = SegmentIds()
        stitchers = {
            channel: CarryOverStitcher(channel, transcriber, settings, language, ids.next)
            for channel in self._tracks
        }
        self._worker = TranscriptionWorker(chunks, stitchers, self._sink)
        self._worker.start()

    @property
    def accepting(self) -> bool:
        return self._accepting

    def accept(self) -> None:
        self._accepting = True

    def receiver(self, channel: Channel) -> Callable[[np.ndarray, float], None]:
        track = self._tracks[channel]

        def on_samples(samples: np.ndarray, at: float) -> None:
            if not self._accepting:
                return
            with track.lock:
                track.writer.write(samples, at)
                track.chunker.feed(samples, at)
            self._observer.on_level(channel, rms_db(samples))

        return on_samples

    def set_paused(self, paused: bool) -> None:
        """Paused: WAVs get silence, chunkers drop audio (their partial window is emitted)."""
        for track in self._tracks.values():
            with track.lock:
                track.writer.paused = paused
                track.chunker.paused = paused

    def stop_capture(self) -> None:
        """Ignore further samples and emit every chunker's last partial window."""
        self._accepting = False
        for track in self._tracks.values():
            with track.lock:
                track.chunker.paused = False
                track.chunker.flush()

    def drain(self) -> None:
        """Transcribe everything queued, flush the stitchers and close the transcript files."""
        self._worker.stop()
        self._sink.close()

    def finalize_wavs(self) -> None:
        """Pad every WAV to the longest one and close them."""
        writers = [track.writer for track in self._tracks.values()]
        total = max(writer.samples_written for writer in writers) / self._rate
        for writer in writers:
            writer.finalize(total)

    def abort(self) -> None:
        """Stop without finalizing (start failed): close every file."""
        self._accepting = False
        self.drain()
        for track in self._tracks.values():
            track.writer.finalize(0)
