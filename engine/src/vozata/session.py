"""A recording session: capture → audio + live transcript → finalization (architecture §6)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout
from vozata.config import ConfigError, Settings
from vozata.diarization.session_diarization import diarize_session
from vozata.domain import Channel, ConversationLanguage, SessionStatus
from vozata.heartbeat import Heartbeat
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_action_items import Extractor, write_session_action_items
from vozata.minutes.session_minutes import EmptyTranscriptError
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
from vozata.session_meta import SessionMeta
from vozata.session_pipeline import CapturePipeline, ChunkerFactory
from vozata.transcription.language_lock import LanguageLock
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


class SessionStartError(RuntimeError):
    """The session could not start; `str()` is the localized message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RecordingSession:
    """Start, pause, resume and stop one recording; `stop()` follows architecture §6 exactly."""

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
            self._c.transcriber_factory,
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

    def stop(self) -> None:
        if self.status not in (SessionStatus.RECORDING, SessionStatus.PAUSED):
            return
        if self.status is SessionStatus.PAUSED:
            self._meta.pause_ended(self._c.clock.now())
        self._stop_capture()  # 1
        self._drain()  # 2
        self._pipeline.finalize_wavs()  # 3
        self._finish()

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
        self._mix()  # 3
        self._release_transcriber()  # 4
        self._identify_speakers()  # 5
        self._write_minutes()  # 6
        self._extract_action_items()  # 6: action items (phase 23)
        self._index_transcript()  # 6: search (phase 22)
        self._meta.ended(self._store.now())  # 7
        self._set_status(SessionStatus.DONE)
        self._stop_heartbeat()

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
        for source in opened:
            source.stop()
        self._release_audio()
        self._store.discard(self.id)

    def _stop_capture(self) -> None:
        for source in self._c.sources.values():
            source.stop()
        self._pipeline.stop_capture()
        self._captured = self._c.clock.now()
        self._meta.captured(self._captured)
        self._release_audio()
        self._set_status(SessionStatus.FINALIZING)

    def _drain(self) -> None:
        self._pipeline.drain()
        dropped = self._pipeline.echo_dropped
        if dropped is not None:
            self._meta.echo_dropped(dropped)

    def _release_audio(self) -> None:
        try:
            self._c.release()
        except Exception:
            _log.exception("Releasing the audio backend failed")

    def _mix(self) -> None:
        try:
            self._audio.write_mix(self.id, self._c.mixer)
        except Exception as error:
            _log.exception("Mixing %s failed", self.id)
            self._error("mix_failed", reason=str(error))

    def _release_transcriber(self) -> None:
        transcriber = self._pipeline.transcriber if self._pipeline is not None else None
        if transcriber is None:
            return
        try:
            transcriber.close()
        except Exception:
            _log.exception("Releasing the transcriber failed")

    def _live_embedder(self) -> Callable[[], SpeakerEmbedder] | None:
        """The embedder for live speaker labels (phase 15); a failed load reports an error."""
        factory = self._c.embedder_factory
        if factory is None:
            return None

        def build() -> SpeakerEmbedder:
            try:
                return factory()
            except Exception as error:
                self._error("live_diarization_failed", reason=self._reason(error))
                raise

        return build

    def _identify_speakers(self) -> None:
        """Diarize the system track (Whisper is already released); a failure keeps `system`
        labels.

        Once speakers are written, `speakers_relabeled` tells clients to reload the transcript:
        the post-session speakers replace the live ones (phase 15).
        """
        if self._c.diarizer_factory is None:
            return
        try:
            found = diarize_session(
                self._store,
                self._audio,
                self.id,
                self._c.diarizer_factory,
                self._settings.min_speakers,
                self._settings.max_speakers,
            )
        except Exception as error:
            _log.warning("Speaker identification for %s failed: %s", self.id, error)
            reason = self._reason(error)
            command = f'python -m vozata diarize "{self._command_target()}"'
            self._error("diarization_failed", reason=reason, command=command)
            return
        if found is not None:
            self._observer.on_speakers_relabeled(self.id)

    def _write_minutes(self) -> None:
        if self._c.minutes is None:
            return
        segments = self._store.load_transcript(self.id)
        if not segments:
            _log.info("No speech in %s; minutes skipped", self.id)
            return
        try:
            labeler = self._c.labeler.with_names(self._store.speaker_names(self.id))
            minutes = self._c.minutes.generate(
                segments, labeler, self._lock.language, self._c.vocabulary
            )
        except Exception as error:
            _log.exception("Generating minutes for %s failed", self.id)
            command = f'python -m vozata minutes "{self._command_target()}"'
            self._error("minutes_failed", reason=str(error), command=command)
            return
        self._store.write_minutes(self.id, minutes + "\n")
        self._observer.on_minutes_ready(self.id)

    def _extract_action_items(self) -> None:
        """After the minutes, with the same model (phase 23); a failure keeps everything else."""
        if self._c.action_items is None:
            return
        try:
            items = write_session_action_items(
                self._store, self.id, self._c.action_items, self._c.labeler
            )
        except EmptyTranscriptError:
            return
        except Exception as error:
            _log.exception("Extracting action items for %s failed", self.id)
            self._error("action_items_failed", reason=str(error))
            return
        self._observer.on_action_items_ready(self.id, len(items))

    def _index_transcript(self) -> None:
        if self._c.search_index is None:
            return
        try:
            self._c.search_index.index_session(self.id, self._store.load_transcript(self.id))
        except Exception as error:
            _log.exception("Indexing %s for search failed", self.id)
            self._error("index_failed", reason=str(error))

    def _command_target(self) -> str:
        """What the CLI commands in error messages take: the session folder (file backend)."""
        folder = self.folder
        return str(folder) if folder is not None else self.id

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
