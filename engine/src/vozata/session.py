"""A recording session: capture → WAVs + live transcript → finalization (architecture §6)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout
from vozata.config import Settings
from vozata.domain import Channel, ConversationLanguage, SessionStatus
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import AudioMixer, AudioSource, Localizer, SessionObserver, Transcriber
from vozata.session_meta import SessionMeta
from vozata.session_pipeline import CapturePipeline
from vozata.storage.session_store import SessionPaths, SessionStore
from vozata.transcription.language_lock import LanguageLock

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
        store: SessionStore,
        components: SessionComponents,
        observer: SessionObserver,
        language: ConversationLanguage,
        open_timeout: float = SOURCE_OPEN_TIMEOUT,
    ) -> None:
        self._settings = settings
        self._store = store
        self._c = components
        self._observer = observer
        self._language = language
        self._open_timeout = open_timeout
        self.status: SessionStatus | None = None
        self._paths: SessionPaths | None = None

    @property
    def paths(self) -> SessionPaths:
        if self._paths is None:
            raise RuntimeError("The session has not started")
        return self._paths

    @property
    def id(self) -> str:
        return self.paths.id

    def start(self) -> None:
        """Load the transcriber, create the session folder and open every source."""
        if self._paths is not None:
            raise RuntimeError("A session can only be started once")
        self._transcriber = self._c.transcriber_factory()
        started_at = self._store.now()
        self._paths = self._store.create(started_at)
        self._meta = SessionMeta(self._store, self.id, started_at, self._settings, self._c)
        self._meta.set_language(self._language, "selected")
        self._lock = LanguageLock(self._language, self._on_language_detected)
        self._pipeline = CapturePipeline(
            self._c.sources,
            self._paths,
            self._settings,
            self._transcriber,
            self._lock,
            self._c.labeler,
            self._observer,
        )
        self._c.clock.start()
        self._pipeline.accept()
        self._open_sources()
        self._set_status(SessionStatus.RECORDING)

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
        self._pipeline.drain()  # 2
        self._finalize_audio()  # 3
        self._release_transcriber()  # 4
        # 5: speaker identification (phase 14)
        self._write_minutes()  # 6
        self._meta.ended(self._store.now())  # 7
        self._set_status(SessionStatus.DONE)

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
        self._transcriber.close()
        self._store.discard(self.id)

    def _stop_capture(self) -> None:
        for source in self._c.sources.values():
            source.stop()
        self._pipeline.stop_capture()
        self._release_audio()
        self._set_status(SessionStatus.FINALIZING)

    def _release_audio(self) -> None:
        try:
            self._c.release()
        except Exception:
            _log.exception("Releasing the audio backend failed")

    def _finalize_audio(self) -> None:
        self._pipeline.finalize_wavs()
        paths = self.paths
        try:
            self._c.mixer.mix(paths.wav(Channel.MIC), paths.wav(Channel.SYSTEM), paths.mixed_wav)
        except Exception as error:
            _log.exception("Mixing %s failed", paths.root)
            self._error("mix_failed", reason=str(error))

    def _release_transcriber(self) -> None:
        try:
            self._transcriber.close()
        except Exception:
            _log.exception("Releasing the transcriber failed")

    def _write_minutes(self) -> None:
        if self._c.minutes is None:
            return
        segments = self._store.load_transcript(self.id)
        if not segments:
            _log.info("No speech in %s; minutes skipped", self.id)
            return
        try:
            minutes = self._c.minutes.generate(segments, self._c.labeler, self._lock.language)
        except Exception as error:
            _log.exception("Generating minutes for %s failed", self.id)
            command = f'python -m vozata minutes "{self.paths.root}"'
            self._error("minutes_failed", reason=str(error), command=command)
            return
        self.paths.minutes_md.write_text(minutes + "\n", encoding="utf-8", newline="\n")
        self._observer.on_minutes_ready(self.id)

    def _on_language_detected(self, language: ConversationLanguage) -> None:
        self._meta.set_language(language, "detected")
        self._observer.on_language_detected(language)

    def _set_status(self, status: SessionStatus) -> None:
        self.status = status
        self._meta.set_status(status)
        self._observer.on_status(status, self._c.clock.now())

    def _start_error(self, code: str, **params: object) -> SessionStartError:
        return SessionStartError(code, self._c.localizer.t(f"errors.session.{code}", **params))

    def _error(self, code: str, **params: object) -> None:
        self._observer.on_error(code, self._c.localizer.t(f"errors.session.{code}", **params))
