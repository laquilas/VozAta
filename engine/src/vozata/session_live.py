"""The live transcription half of a capture pipeline: worker, stitchers, echo filter and sinks."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable, Collection, Sequence

import numpy as np

from vozata.config import Settings
from vozata.diarization.live import LiveSpeakerTagger
from vozata.diarization.live_sink import AudioHistory, LiveSpeakerSink
from vozata.domain import AudioChunk, Channel, TranscriptionResult, TranscriptSegment
from vozata.output.sinks import CompositeSink
from vozata.ports import SessionObserver, SpeakerEmbedder, Transcriber, TranscriptSink
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


class LiveTranscription:
    """Queued chunks → `TranscriptionWorker` → stitchers → [echo filter] → [live speakers] →
    the transcript, the observer and `extra_sinks` (see `CapturePipeline`).

    `uncut(channel)` gives a channel's audio not chunked yet, for the interim text.
    """

    def __init__(
        self,
        chunks: queue.Queue[AudioChunk],
        channels: Collection[Channel],
        transcript: TranscriptSink,
        settings: Settings,
        transcriber_factory: Callable[[], Transcriber],
        language: LanguageLock,
        observer: SessionObserver,
        on_load_failed: Callable[[Exception], None],
        uncut: Callable[[Channel], AudioChunk | None],
        hints: str | None = None,
        speaker_embedder: Callable[[], SpeakerEmbedder] | None = None,
        extra_sinks: Sequence[TranscriptSink] = (),
    ) -> None:
        sinks = CompositeSink([transcript, _ObserverSink(observer), *extra_sinks])
        self.history: AudioHistory | None = None
        self.speakers: LiveSpeakerSink | None = None
        if speaker_embedder is not None and Channel.SYSTEM in channels:
            self.speakers, self.history = _live_speakers(settings, sinks, speaker_embedder)
        tagged: TranscriptSink = self.speakers or sinks
        self.echo = (
            _echo_filter(settings, tagged, observer) if settings.echo_dedupe_enabled else None
        )
        self.sink: TranscriptSink = self.echo or tagged
        self.transcriber = _DeferredTranscriber(transcriber_factory, observer, on_load_failed)
        ids = SegmentIds()
        stitchers = {
            channel: CarryOverStitcher(
                channel,
                self.transcriber,
                settings,
                language,
                ids.next,
                hints=hints,
                context=RollingContext(settings.context_prompt_chars),
            )
            for channel in channels
        }
        partials = None
        if settings.live_partials:
            partials = PartialOptions(
                settings.partial_interval_seconds,
                uncut,
                lambda channel, start, text: observer.on_partial(
                    channel, channel.value, start, text
                ),
            )
        self.worker = TranscriptionWorker(
            chunks,
            stitchers,
            self.sink,
            load=self.transcriber.load,
            partials=partials,
            tick=self.echo.tick if self.echo else lambda: None,
        )

    def start(self) -> None:
        self.worker.start()
        if self.speakers is not None:
            self.speakers.start()

    def close_transcriber(self) -> None:
        loaded = self.transcriber.loaded
        if loaded is not None:
            loaded.close()
