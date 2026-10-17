"""The live part of a session: WAV writers, chunkers, the transcription worker and sinks."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable

import numpy as np

from vozata.audio.chunker import FixedWindowChunker
from vozata.audio.levels import rms_db
from vozata.audio.wav_writer import AlignedWavWriter
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptionResult, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.output.sinks import CompositeSink, JsonlSink, MarkdownSink
from vozata.ports import Chunker, SessionObserver, Transcriber, TranscriptSink
from vozata.storage.session_store import SessionPaths
from vozata.transcription.echo import EchoFilter
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds
from vozata.transcription.worker import PartialOptions, TranscriptionWorker

ChunkerFactory = Callable[[Channel, Callable[[AudioChunk], None]], Chunker]

_log = logging.getLogger(__name__)


def _fixed_windows(settings: Settings) -> ChunkerFactory:
    def build(channel: Channel, on_chunk: Callable[[AudioChunk], None]) -> Chunker:
        return FixedWindowChunker(channel, settings.chunk_seconds, settings.sample_rate, on_chunk)

    return build


class _DeferredTranscriber:
    """The session's transcriber, loaded by the transcription worker once capture is running."""

    def __init__(
        self,
        factory: Callable[[], Transcriber],
        observer: SessionObserver,
        on_failed: Callable[[Exception], None],
    ) -> None:
        self._factory = factory
        self._observer = observer
        self._on_failed = on_failed
        self.loaded: Transcriber | None = None

    def load(self) -> bool:
        self._observer.on_model_loading(True)
        try:
            self.loaded = self._factory()
        except Exception as error:
            _log.exception("Loading the speech model failed")
            self._on_failed(error)
            return False
        finally:
            self._observer.on_model_loading(False)
        return True

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self.loaded is None:
            raise RuntimeError("The speech model is not loaded")
        return self.loaded.transcribe(samples, language, hints, prompt)

    def close(self) -> None:  # the session releases `loaded` itself
        pass


def _echo_filter(
    settings: Settings, sinks: TranscriptSink, observer: SessionObserver
) -> EchoFilter:
    """Echo dedupe in front of the sinks (phase 18); a dropped mic segment also clears the mic
    interim text it had replaced, since no segment will replace it."""

    def clear_partial(segment: TranscriptSegment) -> None:
        if settings.live_partials:
            observer.on_partial(segment.channel, segment.channel.value, segment.start, "")

    return EchoFilter(
        sinks,
        settings.echo_similarity,
        settings.effective_echo_hold_seconds,
        on_dropped=clear_partial,
    )


class _ObserverSink:
    def __init__(self, observer: SessionObserver) -> None:
        self._observer = observer

    def emit(self, segment: TranscriptSegment) -> None:
        self._observer.on_segment(segment)

    def close(self) -> None:
        pass


class _Track:
    """One channel's writer and chunker; the lock serializes capture writes and pause toggles."""

    def __init__(self, writer: AlignedWavWriter, chunker: Chunker) -> None:
        self.writer = writer
        self.chunker = chunker
        self.lock = threading.Lock()


class CapturePipeline:
    """Route captured samples to WAVs and transcription; segments go to files and the observer.

    `receiver(channel)` is the callback for that channel's source. Samples arriving after
    `stop_capture()` (or before `accept()`) are ignored. `start_transcription()` loads the
    transcriber on the worker thread; chunks captured meanwhile wait in the queue. A failed load
    calls `on_load_failed` and the audio is only written to the WAVs. Chunkers come from
    `chunker_factory` (`CHUNKERS` in `bootstrap.py`); without one, fixed `CHUNK_SECONDS` windows
    are used.
    """

    def __init__(
        self,
        channels: Iterable[Channel],
        paths: SessionPaths,
        settings: Settings,
        transcriber_factory: Callable[[], Transcriber],
        language: LanguageLock,
        labeler: SpeakerLabeler,
        observer: SessionObserver,
        chunker_factory: ChunkerFactory | None = None,
        on_load_failed: Callable[[Exception], None] = lambda error: None,
    ) -> None:
        self._rate = settings.sample_rate
        new_chunker = chunker_factory or _fixed_windows(settings)
        self._observer = observer
        self._accepting = False
        chunks: queue.Queue[AudioChunk] = queue.Queue()
        self._tracks = {
            channel: _Track(
                AlignedWavWriter(paths.wav(channel), self._rate),
                new_chunker(channel, chunks.put),
            )
            for channel in channels
        }
        sinks = CompositeSink(
            [
                JsonlSink(paths.transcript_jsonl),
                MarkdownSink(paths.transcript_md, labeler),
                _ObserverSink(observer),
            ]
        )
        self._echo = (
            _echo_filter(settings, sinks, observer) if settings.echo_dedupe_enabled else None
        )
        self._sink: TranscriptSink = self._echo or sinks
        self._transcriber = _DeferredTranscriber(transcriber_factory, observer, on_load_failed)
        transcriber = self._transcriber
        ids = SegmentIds()
        stitchers = {
            channel: CarryOverStitcher(channel, transcriber, settings, language, ids.next)
            for channel in self._tracks
        }
        partials = None
        if settings.live_partials:
            partials = PartialOptions(
                settings.partial_interval_seconds,
                self._uncut_audio,
                lambda channel, start, text: observer.on_partial(
                    channel, channel.value, start, text
                ),
            )
        self._worker = TranscriptionWorker(
            chunks,
            stitchers,
            self._sink,
            load=transcriber.load,
            partials=partials,
            tick=self._echo.tick if self._echo else lambda: None,
        )

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def echo_dropped(self) -> int | None:
        """Mic segments dropped as echo so far; None when `ECHO_DEDUPE_ENABLED` is off."""
        return self._echo.dropped if self._echo else None

    @property
    def transcriber(self) -> Transcriber | None:
        """The loaded transcriber (None before or after a failed load)."""
        return self._transcriber.loaded

    def accept(self) -> None:
        self._accepting = True

    def start_transcription(self) -> None:
        """Load the transcriber on the worker thread, then transcribe the queued chunks."""
        self._worker.start()

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

    def _uncut_audio(self, channel: Channel) -> AudioChunk | None:
        """The chunker's audio not emitted yet (interim text); taken under the track lock."""
        track = self._tracks[channel]
        with track.lock:
            return track.chunker.buffered()

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
        """Transcribe everything queued, flush the stitchers and close the transcript files.

        Closing releases the mic segments the echo filter still holds (`EchoFilter.flush()`).
        """
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
