"""The capture side of a session: audio writers, level meters and, when live, chunkers feeding
the live transcription (`session_live.py`)."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable, Sequence

import numpy as np

from vozata.audio.chunker import ChunkerFactory, fixed_windows
from vozata.audio.levels import rms_db
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel
from vozata.ports import (
    AudioTrackWriter,
    Chunker,
    SessionObserver,
    SpeakerEmbedder,
    Transcriber,
    TranscriptSink,
)
from vozata.session_live import LiveTranscription
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.stitcher import SegmentIds

_log = logging.getLogger(__name__)


class _Track:
    """One channel's writer and (live) chunker; the lock serializes capture writes and pause
    toggles."""

    def __init__(self, writer: AudioTrackWriter, chunker: Chunker | None) -> None:
        self.writer = writer
        self.chunker = chunker
        self.lock = threading.Lock()


class CapturePipeline:
    """Route captured samples to the audio writers and, when `live`, to transcription; segments
    go to the transcript from `open_transcript()` and the observer.

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

    With `live=False` (phase 41, audio only) only the writers and level meters run: no chunker,
    worker, transcript files or model; the transcription arguments are not used.
    """

    def __init__(
        self,
        channels: Iterable[Channel],
        open_writer: Callable[[Channel], AudioTrackWriter],
        open_transcript: Callable[[], TranscriptSink],
        settings: Settings,
        transcriber_factory: Callable[[], Transcriber],
        language: LanguageLock,
        observer: SessionObserver,
        chunker_factory: ChunkerFactory | None = None,
        on_load_failed: Callable[[Exception], None] = lambda error: None,
        hints: str | None = None,
        speaker_embedder: Callable[[], SpeakerEmbedder] | None = None,
        extra_sinks: Sequence[TranscriptSink] = (),
        live: bool = True,
    ) -> None:
        self._rate = settings.sample_rate
        self._observer = observer
        self._accepting = False
        self._live: LiveTranscription | None = None
        # phase 63: what turning live transcription on again during the recording needs
        self._rebuild = (
            open_transcript,
            settings,
            transcriber_factory,
            language,
            chunker_factory or fixed_windows(settings),
            on_load_failed,
        )
        self._hints = hints
        self._external: dict[Channel, Chunker] = {}  # chunkers fed by a separate source (63)
        self._external_lock = threading.Lock()
        self._draining: list[threading.Thread] = []  # live parts turned off, still finishing
        chunks: queue.Queue[AudioChunk] = queue.Queue()
        new_chunker = (chunker_factory or fixed_windows(settings)) if live else None
        self._tracks = {
            channel: _Track(
                open_writer(channel),
                new_chunker(channel, self._queue(chunks)) if new_chunker else None,
            )
            for channel in channels
        }
        if live:
            self._live = LiveTranscription(
                chunks,
                list(self._tracks),
                open_transcript(),
                settings,
                transcriber_factory,
                language,
                observer,
                on_load_failed,
                self._uncut_audio,
                hints=hints,
                speaker_embedder=speaker_embedder,
                extra_sinks=extra_sinks,
            )

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def echo_dropped(self) -> int | None:
        """Mic segments dropped as echo so far; None when `ECHO_DEDUPE_ENABLED` is off or the
        pipeline is audio only."""
        echo = self._live.echo if self._live else None
        return echo.dropped if echo else None

    @property
    def transcriber(self) -> Transcriber | None:
        """The loaded transcriber (None before or after a failed load, and when audio only)."""
        return self._live.transcriber.loaded if self._live else None

    def accept(self) -> None:
        self._accepting = True

    @property
    def live(self) -> bool:
        """Live transcription runs (phase 63: it can be turned off during the recording)."""
        return self._live is not None

    def add_sink(self, sink: TranscriptSink) -> None:
        """Send the committed segments to `sink` too from now on (e.g. a translation worker)."""
        if self._live is None:
            raise RuntimeError("The pipeline records audio only")
        self._live.sinks.add(sink)

    def remove_sink(self, sink: TranscriptSink) -> None:
        if self._live is not None:
            self._live.sinks.remove(sink)

    def set_hints(self, hints: str | None) -> None:
        """The meeting terms changed (phase 63): every later transcription uses them."""
        self._hints = hints
        if self._live is not None:
            self._live.set_hints(hints)

    def disable_live(self, on_done: Callable[[], None]) -> None:
        """Turn live transcription off during the recording (phase 63); returns at once.

        The chunkers emit their last window and are dropped; on a thread, the worker transcribes
        what is queued, the transcript files (and the sinks: translation, voice commands) close,
        the transcriber closes and `on_done()` runs. Audio keeps being written.
        """
        live = self._live
        if live is None:
            on_done()
            return
        for track in self._tracks.values():
            with track.lock:
                if track.chunker is not None:
                    track.chunker.flush()
                    track.chunker = None
        with self._external_lock:
            for chunker in self._external.values():
                chunker.flush()
            self._external = {}
        self._live = None

        def drain() -> None:
            for part, what in (
                (live.worker.stop, "Draining the live transcription"),
                (live.sink.close, "Closing the transcript"),
                (live.close_transcriber, "Releasing the transcriber"),
            ):
                try:
                    part()
                except Exception:
                    _log.exception("%s failed", what)
            on_done()

        thread = threading.Thread(target=drain, name="live-off", daemon=True)
        self._draining.append(thread)
        thread.start()

    def enable_live(
        self, ids: SegmentIds, channels: Iterable[Channel] | None = None
    ) -> dict[Channel, Callable[[np.ndarray, float], None]]:
        """Turn live transcription on during the recording (phase 63).

        New chunkers and a new live transcription (segment ids continue with `ids`) are fed by
        the returned callbacks, not by the capture: the caller replays the recording from the
        transcript's resume point into them, then follows it, so the transcript stays in order.
        """
        if self._live is not None:
            raise RuntimeError("Live transcription already runs")
        open_transcript, settings, transcriber_factory, language, new_chunker, failed = (
            self._rebuild
        )
        chunks: queue.Queue[AudioChunk] = queue.Queue()
        wanted = list(channels or self._tracks)
        with self._external_lock:
            self._external = {
                channel: new_chunker(channel, self._queue(chunks)) for channel in wanted
            }
        self._live = LiveTranscription(
            chunks,
            wanted,
            open_transcript(),
            settings,
            transcriber_factory,
            language,
            self._observer,
            failed,
            self._uncut_audio,
            hints=self._hints,
            ids=ids,
        )
        self._live.start()

        def feeder(channel: Channel) -> Callable[[np.ndarray, float], None]:
            def feed(samples: np.ndarray, at: float) -> None:
                with self._external_lock:
                    chunker = self._external.get(channel)
                    if chunker is not None:
                        chunker.feed(samples, at)

            return feed

        return {channel: feeder(channel) for channel in wanted}

    def start_transcription(self) -> None:
        """Load the transcriber on the worker thread, then transcribe the queued chunks."""
        if self._live is None:
            raise RuntimeError("The pipeline records audio only")
        self._live.start()

    def receiver(self, channel: Channel) -> Callable[[np.ndarray, float], None]:
        track = self._tracks[channel]

        def on_samples(samples: np.ndarray, at: float) -> None:
            if not self._accepting:
                return
            with track.lock:
                track.writer.write(samples, at)
                if track.chunker is not None:
                    track.chunker.feed(samples, at)
            self._observer.on_level(channel, rms_db(samples))

        return on_samples

    def _queue(self, chunks: queue.Queue[AudioChunk]) -> Callable[[AudioChunk], None]:
        """Queue a chunk for transcription; system chunks are also kept for live speakers."""

        def put(chunk: AudioChunk) -> None:
            history = self._live.history if self._live else None
            if history is not None and chunk.channel is Channel.SYSTEM:
                history.add(chunk)
            chunks.put(chunk)

        return put

    def _uncut_audio(self, channel: Channel) -> AudioChunk | None:
        """The chunker's audio not emitted yet (interim text); taken under the track lock."""
        track = self._tracks[channel]
        with track.lock:
            if track.chunker is not None:
                return track.chunker.buffered()
        with self._external_lock:
            external = self._external.get(channel)
            return external.buffered() if external is not None else None

    def set_paused(self, paused: bool) -> None:
        """Paused: WAVs get silence, chunkers drop audio (their partial window is emitted)."""
        for track in self._tracks.values():
            with track.lock:
                track.writer.paused = paused
                if track.chunker is not None:
                    track.chunker.paused = paused
        with self._external_lock:
            for chunker in self._external.values():
                chunker.paused = paused

    def stop_capture(self) -> None:
        """Ignore further samples and emit every chunker's last partial window."""
        self._accepting = False
        for track in self._tracks.values():
            with track.lock:
                if track.chunker is not None:
                    track.chunker.paused = False
                    track.chunker.flush()
        with self._external_lock:
            for chunker in self._external.values():
                chunker.paused = False
                chunker.flush()

    def drain(self) -> None:
        """Transcribe everything queued, flush the stitchers and close the transcript files.

        Closing releases the mic segments the echo filter still holds (`EchoFilter.flush()`).
        """
        if self._live is not None:
            self._live.worker.stop()
            self._live.sink.close()

    def abandon(self, on_closed: Callable[[], None]) -> None:
        """Stop without draining (phase 40); returns at once.

        The worker finishes the chunk (or model load) in hand and skips its backlog; then, on its
        thread, the sinks are closed (the echo filter releases the mic segments it holds), the
        loaded transcriber is closed, the WAVs are finalized and `on_closed()` runs. Audio only,
        the WAVs are finalized and `on_closed()` runs on the caller's thread. A failing part is
        logged and the next one still runs.
        """
        self._accepting = False
        live = self._live
        parts = [(self.finalize_wavs, "Finalizing the WAVs")]
        if live is not None:
            parts[:0] = [
                (live.sink.close, "Closing the transcript"),
                (live.close_transcriber, "Releasing the transcriber"),
            ]

        def close() -> None:
            for thread in self._draining:  # a live part turned off during the recording (63)
                thread.join()
            for part, what in parts:
                try:
                    part()
                except Exception:
                    _log.exception("%s failed", what)
            on_closed()

        if live is None:
            close()
        else:
            live.worker.abandon(close)

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
