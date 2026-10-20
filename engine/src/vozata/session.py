"""A recording session: capture → audio + live transcript → finalization (architecture §6)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout
from vozata.config import ConfigError, Settings
from vozata.domain import Channel, ConversationLanguage, SessionStatus
from vozata.heartbeat import Heartbeat
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_action_items import Extractor
from vozata.minutes.template_repository import DEFAULT_TEMPLATE
from vozata.ports import (
    AudioMixer,
    AudioSource,
    Diarizer,
    Localizer,
    SessionAudio,
    SessionObserver,
    SessionRepository,
    SpeakerEmbedder,
    Transcriber,
    TranscriptSearch,
    Translator,
)
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.job import ProcessingJob, run_job_inline
from vozata.processing.live_lease import LiveGpuLease, LiveModelTurn, ModelLoadSkipped
from vozata.processing.session_job import JobParts, session_job, transcribe_weight
from vozata.session_finisher import SessionFinisher
from vozata.session_meta import SessionMeta
from vozata.session_pipeline import CapturePipeline, ChunkerFactory
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline import OfflineTranscription
from vozata.translation.live import live_translation
from vozata.translation.worker import TranslationWorker
from vozata.vocabulary import build_hints

SOURCE_OPEN_TIMEOUT = 20.0  # a WASAPI open can hang in the driver (phase 02 notes)

_log = logging.getLogger(__name__)


class Clock(Protocol):
    def start(self) -> None: ...

    def now(self) -> float: ...


@dataclass(frozen=True)
class SessionComponents:
    """Providers wired by `bootstrap.py`; the session depends only on their ports."""

    sources: Mapping[Channel, AudioSource]
    device_names: Mapping[Channel, str]
    clock: Clock
    transcriber_factory: Callable[[], Transcriber]
    mixer: AudioMixer
    minutes: MinutesGenerator | None
    localizer: Localizer
    labeler: SpeakerLabeler
    release: Callable[[], None] = lambda: None  # frees the audio backend once capture ended
    chunker_factory: ChunkerFactory | None = None  # None: fixed CHUNK_SECONDS windows
    diarizer_factory: Callable[[], Diarizer] | None = None  # None: no speaker identification
    search_index: TranscriptSearch | None = None  # None: the session is not indexed (22)
    minutes_template: str = DEFAULT_TEMPLATE  # stored in session.json (phase 20)
    vocabulary: tuple[str, ...] = ()  # session + glossary terms (phase 19), session terms first
    action_items: Extractor | None = None  # None: no action items at stop (phase 23)
    embedder_factory: Callable[[], SpeakerEmbedder] | None = None  # None: no live speakers
    translate_to: str | None = None  # live translation language (phase 29); None = off
    translator_factory: Callable[[], Translator] | None = None  # built on the translation thread
    title: str | None = None  # meeting title at start (phase 35), normalized; None = untitled
    gate: GpuGate | None = None  # shared with the processing queue (phase 40); None = no gate
    gpu_usage: GpuUsage | None = None  # which models use the local GPU (phase 40)
    live_models: LiveModelTurn | None = None  # shared by `serve` sessions (phase 40); None = own


class SessionStartError(RuntimeError):
    """The session could not start; `str()` is the localized message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RecordingSession:
    """Start, pause, resume and stop one recording (architecture §6).

    `stop_capture()` ends the recording at once and hands the meeting to a processing job
    (phase 40); `stop()` (CLI `record`) runs that same job inline.
    """

    def __init__(
        self,
        settings: Settings,
        store: SessionRepository,
        audio: SessionAudio,
        components: SessionComponents,
        observer: SessionObserver,
        language: ConversationLanguage,
        open_timeout: float = SOURCE_OPEN_TIMEOUT,
    ) -> None:
        self._settings = settings
        self._store = store
        self._audio = audio
        self._c = components
        self._observer = observer
        self._language = language
        self._open_timeout = open_timeout
        self.status: SessionStatus | None = None
        self._id: str | None = None
        self._captured: float | None = None  # recorded length, fixed once capture stops
        self._heartbeat: Heartbeat | None = None  # `session.json` autosave (phase 17)
        self._pipeline: CapturePipeline | None = None  # None until `start()`, and on `recover()`
        self._gpu = LiveGpuLease(components.gate, components.gpu_usage)
        self._abandoned = threading.Event()  # set at Stop: a live model not loaded yet never loads

    @property
    def id(self) -> str:
        if self._id is None:
            raise RuntimeError("The session has not started")
        return self._id

    @property
    def folder(self) -> Path | None:
        """The session folder (file backend), else None; for messages only."""
        return self._store.folder(self.id)

    @property
    def duration_seconds(self) -> float:
        """Session time so far (pauses included); 0 before `start()`, fixed after capture."""
        if self._captured is not None:
            return self._captured
        return self._c.clock.now() if self.status is not None else 0.0

    def start(self) -> None:
        """Create the session and open every source, then load the transcriber.

        `recording` is reported as soon as the sources are open; the speech model loads on the
        transcription thread (`on_model_loading`) and audio captured meanwhile is transcribed
        once it is ready.
        """
        if self._id is not None:
            raise RuntimeError("A session can only be started once")
        started_at = self._store.now()
        self._id = self._store.create(started_at)
        self._meta = SessionMeta(self._store, self.id, started_at, self._settings, self._c)
        self._meta.set_language(self._language, "selected")
        self._lock = LanguageLock(self._language, self._on_language_detected)
        translation = self._live_translation()
        self._pipeline = CapturePipeline(
            self._c.sources,
            lambda channel: self._audio.open_writer(self.id, channel),
            self._store.open_transcript(self.id, self._c.labeler),
            self._settings,
            self._live_transcriber,
            self._lock,
            self._observer,
            self._c.chunker_factory,
            lambda error: self._error("model_failed", reason=str(error)),
            hints=build_hints(self._c.vocabulary),
            speaker_embedder=self._live_embedder(),
            extra_sinks=[translation] if translation else [],
        )
        self._c.clock.start()
        self._pipeline.accept()
        self._open_sources()
        self._set_status(SessionStatus.RECORDING)
        self._start_heartbeat()
        self._pipeline.start_transcription()
        if translation:
            translation.start()

    def pause(self) -> None:
        if self.status is not SessionStatus.RECORDING:
            return
        self._pipeline.set_paused(True)
        self._meta.pause_started(self._c.clock.now())
        self._set_status(SessionStatus.PAUSED)

    def resume(self) -> None:
        if self.status is not SessionStatus.PAUSED:
            return
        self._meta.pause_ended(self._c.clock.now())
        self._pipeline.set_paused(False)
        self._set_status(SessionStatus.RECORDING)

    def set_title(self, title: str | None) -> None:
        """Rename the meeting (phase 35), while recording or finalizing; None clears the title."""
        self._meta.set_title(title)

    def stop(self) -> None:
        """Stop capture, then run the meeting's processing job on this thread (CLI)."""
        if self.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
            return
        run_job_inline(self.processing_job(self.stop_capture()))

    def stop_capture(self) -> threading.Event:
        """End the recording now (architecture §6, step 1); the live transcription is abandoned.

        Sources stop, `capture_ended_at` and the length are written, PortAudio is released and the
        status becomes `finalizing`. The returned event is set once the abandoned pipeline closed
        its transcript files and WAVs (and the GPU lease is given back); it is already set when
        nothing was recording. A failing part (e.g. `session.json` locked by OneDrive) is logged
        and the rest still runs: the pipeline is always abandoned, so the live model and the GPU
        lease are always released and `closed` is always set.
        """
        closed = threading.Event()
        if self.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
            closed.set()
            return closed
        paused = self.status is SessionStatus.PAUSED
        captured = self._captured = self._c.clock.now()
        self.status = SessionStatus.FINALIZING  # no second stop, whatever fails below
        parts: list[tuple[str, Callable[[], None]]] = []
        if paused:
            parts.append(("Closing the open pause", lambda: self._meta.pause_ended(captured)))
        parts += [("Stopping a source", source.stop) for source in self._c.sources.values()]
        parts += [
            ("Flushing the chunkers", self._pipeline.stop_capture),
            (
                "Saving the capture end",
                lambda: self._meta.capture_ended(self._store.now(), captured),
            ),
            ("Releasing the audio backend", self._release_audio),
            ("Saving the status", lambda: self._meta.set_status(SessionStatus.FINALIZING)),
            ("Reporting the status", lambda: self._observer.on_status(self.status, captured)),
            ("Stopping the autosave", self._stop_heartbeat),  # the job owns `session.json` now
        ]
        try:
            for what, part in parts:
                try:
                    part()
                except Exception:
                    _log.exception("%s at stop failed", what)
        finally:
            self._abandoned.set()
            if self._c.live_models is not None:
                self._c.live_models.stopping(closed)
            self._pipeline.abandon(lambda: self._pipeline_closed(closed))
        return closed

    def processing_job(self, closed: threading.Event | None) -> ProcessingJob:
        """The rest of this meeting (transcribe the rest, mix, speakers, minutes, index, done) with
        this session's own components; never cancelled, so they are reused across steps."""
        parts = JobParts(
            finisher=lambda models: self._finisher(),
            transcription=self._offline,
            diarize=self._c.diarizer_factory is not None,
            minutes=self._c.minutes is not None,
            action_items=self._c.action_items is not None,
        )
        usage = self._c.gpu_usage or GpuUsage(speech=False, speakers=False, llm=False)
        weight = transcribe_weight(self._store, self.id, self.duration_seconds)
        return session_job(
            self.id, parts, usage, weight=weight, closed=closed, on_finished=self._done
        )

    def _pipeline_closed(self, closed: threading.Event) -> None:
        """On the abandoned worker's thread, once its files are closed."""
        try:
            dropped = self._pipeline.echo_dropped
            if dropped is not None:
                self._meta.echo_dropped(dropped)
        except Exception:
            _log.exception("Saving the echo count failed")
        finally:
            self._gpu.release()
            closed.set()

    def _offline(self) -> OfflineTranscription:
        return OfflineTranscription(
            self._settings,
            self._store,
            self._audio,
            self._c.transcriber_factory,
            self._c.labeler,
            self._lock,
            build_hints(self._c.vocabulary),
            self._c.chunker_factory,
            on_segment=self._observer.on_segment,  # CLI: the lines after Stop are printed too
        )

    def _done(self) -> None:
        self._finisher().ended(self._store.now())
        self.status = SessionStatus.DONE
        self._observer.on_status(SessionStatus.DONE, self.duration_seconds)

    def _live_transcriber(self) -> Transcriber:
        """The live model, loaded on the worker thread once it may (see `_before_model`)."""
        self._before_model(self._gpu.hold_speech)
        return self._c.transcriber_factory()

    def _before_model(self, hold: Callable[[], None]) -> None:
        """Before a live model loads: the previous session's live models are closed, then `hold`
        takes the GPU gate when that model runs on the local GPU (pre-empting the queue's GPU
        step). Raises `ModelLoadSkipped` once this session stopped: an abandoned session never
        takes the gate nor loads a model only to close it."""
        if self._abandoned.is_set():
            raise ModelLoadSkipped
        if self._c.live_models is not None:
            self._c.live_models.wait()
        if self._abandoned.is_set():  # stopped while the previous session's models closed
            raise ModelLoadSkipped
        hold()

    def recover(self, session_id: str, duration_seconds: float) -> None:
        """Finish an interrupted session whose audio and transcript were repaired (phase 17).

        Runs the same `_finish()` sequence as `stop()` (mix onwards), so every stop step also
        runs on recovery. `duration_seconds` is the recorded length found in the repaired audio.
        """
        if self._id is not None:
            raise RuntimeError("A session can only be started or recovered once")
        meta = self._store.read_meta(session_id)
        self._id = session_id
        self._meta = SessionMeta.restore(self._store, session_id, meta)
        language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
        self._lock = LanguageLock(language, self._on_language_detected)
        self._captured = duration_seconds
        self._meta.captured(duration_seconds)
        self._set_status(SessionStatus.FINALIZING)
        self._start_heartbeat()
        self._finish()

    def _finish(self) -> None:
        """Stop steps 3 (mix) to 7, shared by `stop()` and `recover()` (phase 17)."""
        finisher = self._finisher()
        token = CancelToken()  # a live stop is never cancelled
        finisher.mix()  # 3
        finisher.identify_speakers(token)  # 5
        finisher.write_minutes(token)  # 6
        finisher.extract_action_items(token)  # 6: action items (phase 23)
        finisher.index()  # 6: search (phase 22)
        finisher.ended(self._store.now())  # 7
        self._set_status(SessionStatus.DONE)
        self._stop_heartbeat()

    def _finisher(self) -> SessionFinisher:
        return SessionFinisher(
            self._settings,
            self._store,
            self._audio,
            self._c,
            self._observer,
            self.id,
            self._lock,
            lambda: self._meta.title,
            self._meta,
        )

    def _start_heartbeat(self) -> None:
        """Save `last_heartbeat_at` and the length so far every `AUTOSAVE_SECONDS` until done, so
        a crash leaves a recent `session.json` (phase 17)."""
        self._heartbeat = Heartbeat(self._settings.autosave_seconds, self._autosave, "autosave")
        self._heartbeat.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.stop()

    def _autosave(self) -> None:
        self._meta.heartbeat(self._store.now(), self.duration_seconds)

    def _live_translation(self) -> TranslationWorker | None:
        """The translation worker (phase 29), closed with the transcript files at step 2."""
        if self._c.translate_to is None or self._c.translator_factory is None:
            return None
        return live_translation(
            self._c.translate_to,
            self._c.translator_factory,
            self._store.open_translations(self.id),
            self._lock.current,
            self._observer,
            lambda error: self._error("translation_failed", reason=str(error)),
        )

    def _open_sources(self) -> None:
        opened: list[AudioSource] = []
        for channel, source in self._c.sources.items():
            name = self._c.device_names.get(channel, channel.value)
            try:
                open_with_timeout(
                    source,
                    self._pipeline.receiver(channel),
                    self._open_timeout,
                    lambda: self._pipeline.accepting,
                )
            except SourceOpenTimeoutError:
                self._abort(opened)
                raise self._start_error(
                    "device_timeout", device=name, seconds=self._open_timeout
                ) from None
            except Exception as error:
                self._abort(opened)
                raise self._start_error("device_failed", device=name, reason=str(error)) from error
            opened.append(source)

    def _abort(self, opened: list[AudioSource]) -> None:
        self._pipeline.abort()
        self._gpu.release()
        for source in opened:
            source.stop()
        self._release_audio()
        self._store.discard(self.id)

    def _release_audio(self) -> None:
        try:
            self._c.release()
        except Exception:
            _log.exception("Releasing the audio backend failed")

    def _live_embedder(self) -> Callable[[], SpeakerEmbedder] | None:
        """The embedder for live speaker labels (phase 15); a failed load reports an error."""
        factory = self._c.embedder_factory
        if factory is None:
            return None

        def build() -> SpeakerEmbedder:
            self._before_model(self._gpu.hold_speakers)
            try:
                return factory()
            except Exception as error:
                self._error("live_diarization_failed", reason=self._reason(error))
                raise

        return build

    def _reason(self, error: Exception) -> str:
        return error.render(self._c.localizer) if isinstance(error, ConfigError) else str(error)

    def _on_language_detected(self, language: ConversationLanguage) -> None:
        self._meta.set_language(language, "detected")
        self._observer.on_language_detected(language)

    def _set_status(self, status: SessionStatus) -> None:
        self.status = status
        self._meta.set_status(status)
        self._observer.on_status(status, self.duration_seconds)

    def _start_error(self, code: str, **params: object) -> SessionStartError:
        return SessionStartError(code, self._c.localizer.t(f"errors.session.{code}", **params))

    def _error(self, code: str, **params: object) -> None:
        self._observer.on_error(code, self._c.localizer.t(f"errors.session.{code}", **params))
