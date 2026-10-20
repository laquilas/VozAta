"""The live part of a session: audio writers, chunkers, the transcription worker and sinks."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable, Sequence

import numpy as np

from vozata.audio.chunker import ChunkerFactory, fixed_windows
from vozata.audio.levels import rms_db
from vozata.config import Settings
from vozata.diarization.live import LiveSpeakerTagger
from vozata.diarization.live_sink import AudioHistory, LiveSpeakerSink
from vozata.domain import AudioChunk, Channel, TranscriptionResult, TranscriptSegment
from vozata.output.sinks import CompositeSink
from vozata.ports import (
    AudioTrackWriter,
    Chunker,
    SessionObserver,
    SpeakerEmbedder,
    Transcriber,
    TranscriptSink,
)
from vozata.processing.live_lease import ModelLoadSkipped
from vozata.transcription.context import RollingContext
from vozata.transcription.echo import EchoFilter
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds
from vozata.transcription.worker import PartialOptions, TranscriptionWorker

_log = logging.getLogger(__name__)


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
        except ModelLoadSkipped:
            return False  # the session stopped before its model loaded: nothing to report
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

    return EchoFilter.from_settings(settings, sinks, on_dropped=clear_partial)


def _live_speakers(
    settings: Settings, sinks: TranscriptSink, embedder: Callable[[], SpeakerEmbedder]
) -> tuple[LiveSpeakerSink, AudioHistory]:
    """Live speaker labels (phase 15) on their own thread, in front of the sinks."""
    history = AudioHistory(settings.sample_rate, 60.0 + settings.max_carry_seconds)

    def load() -> LiveSpeakerTagger:
        return LiveSpeakerTagger(
            embedder(), settings.speaker_similarity_threshold, max_seconds=settings.chunk_seconds
        )

    return LiveSpeakerSink(sinks, load, history), history


class _ObserverSink:
    def __init__(self, observer: SessionObserver) -> None:
        self._observer = observer

    def emit(self, segment: TranscriptSegment) -> None:
        self._observer.on_segment(segment)

    def close(self) -> None:
        pass


class _Track:
    """One channel's writer and chunker; the lock serializes capture writes and pause toggles."""

    def __init__(self, writer: AudioTrackWriter, chunker: Chunker) -> None:
        self.writer = writer
        self.chunker = chunker
        self.lock = threading.Lock()


class CapturePipeline:
    """Route captured samples to the audio writers and transcription; segments go to the
    stored `transcript` and the observer.

    `open_writer(channel)` gives each channel's `AudioTrackWriter` (`AudioStore.open_writer`).
    `receiver(channel)` is the callback for that channel's source. Samples arriving after
    `stop_capture()` (or before `accept()`) are ignored. `start_transcription()` loads the
    transcriber on the worker thread; chunks captured meanwhile wait in the queue. A failed load
    calls `on_load_failed` and the audio is only written to the WAVs. Chunkers come from
    `chunker_factory` (`CHUNKERS` in `bootstrap.py`); without one, fixed `CHUNK_SECONDS` windows
    are used. `hints` (the session vocabulary, phase 19) go with every transcription, and each
    channel gets its own rolling context prompt of `CONTEXT_PROMPT_CHARS`. With a
    `speaker_embedder` (`LIVE_DIARIZATION_ENABLED`), system segments get live `system:<n>`
    speakers from a `LiveSpeakerSink` between the echo filter and the sinks. `extra_sinks` get
    every committed segment after echo dedupe (and live speakers), next to the transcript files
    (e.g. the translation worker, phase 29); they must return quickly and are closed by `drain()`.
    """

    def __init__(
        self,
        channels: Iterable[Channel],
        open_writer: Callable[[Channel], AudioTrackWriter],
        transcript: TranscriptSink,
        settings: Settings,
        transcriber_factory: Callable[[], Transcriber],
        language: LanguageLock,
        observer: SessionObserver,
        chunker_factory: ChunkerFactory | None = None,
        on_load_failed: Callable[[Exception], None] = lambda error: None,
        hints: str | None = None,
        speaker_embedder: Callable[[], SpeakerEmbedder] | None = None,
        extra_sinks: Sequence[TranscriptSink] = (),
    ) -> None:
        self._rate = settings.sample_rate
        new_chunker = chunker_factory or fixed_windows(settings)
        self._observer = observer
        self._accepting = False
        chunks: queue.Queue[AudioChunk] = queue.Queue()
        self._history: AudioHistory | None = None
        self._live: LiveSpeakerSink | None = None
        self._tracks = {
            channel: _Track(
                open_writer(channel),
                new_chunker(channel, self._queue(chunks)),
            )
            for channel in channels
        }
        sinks = CompositeSink(
            [
                transcript,
                _ObserverSink(observer),
                *extra_sinks,
            ]
        )
        if speaker_embedder is not None and Channel.SYSTEM in self._tracks:
            self._live, self._history = _live_speakers(settings, sinks, speaker_embedder)
        tagged: TranscriptSink = self._live or sinks
        self._echo = (
            _echo_filter(settings, tagged, observer) if settings.echo_dedupe_enabled else None
        )
        self._sink: TranscriptSink = self._echo or tagged
        self._transcriber = _DeferredTranscriber(transcriber_factory, observer, on_load_failed)
        transcriber = self._transcriber
        ids = SegmentIds()
        stitchers = {
            channel: CarryOverStitcher(
                channel,
                transcriber,
                settings,
                language,
                ids.next,
                hints=hints,
                context=RollingContext(settings.context_prompt_chars),
            )
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
        if self._live is not None:
            self._live.start()

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

    def _queue(self, chunks: queue.Queue[AudioChunk]) -> Callable[[AudioChunk], None]:
        """Queue a chunk for transcription; system chunks are also kept for live speakers."""

        def put(chunk: AudioChunk) -> None:
            if self._history is not None and chunk.channel is Channel.SYSTEM:
                self._history.add(chunk)
            chunks.put(chunk)

        return put

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

    def abandon(self, on_closed: Callable[[], None]) -> None:
        """Stop without draining (phase 40); returns at once.

        The worker finishes the chunk (or model load) in hand and skips its backlog; then, on its
        thread, the sinks are closed (the echo filter releases the mic segments it holds), the
        loaded transcriber is closed, the WAVs are finalized and `on_closed()` runs. A failing
        part is logged and the next one still runs.
        """
        self._accepting = False

        def close() -> None:
            for part, what in (
                (self._sink.close, "Closing the transcript"),
                (self._close_transcriber, "Releasing the transcriber"),
                (self.finalize_wavs, "Finalizing the WAVs"),
            ):
                try:
                    part()
                except Exception:
                    _log.exception("%s failed", what)
            on_closed()

        self._worker.abandon(close)

    def _close_transcriber(self) -> None:
        loaded = self._transcriber.loaded
        if loaded is not None:
            loaded.close()

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
