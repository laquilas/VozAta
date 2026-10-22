"""The stop steps after capture (architecture §6, steps 3 and 5-7), run from stored data.

`RecordingSession` runs them right after a stop or a recovery; a processing queue can run them
later and cancel the GPU ones (phase 40). Each step reports its own failure through the observer
and never stops the next one; a cancelled step raises `StepCancelled` and reports nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from vozata.config import ConfigError, Settings
from vozata.diarization.session_diarization import diarize_session
from vozata.domain import SessionStatus
from vozata.minutes.session_action_items import write_session_action_items
from vozata.minutes.session_minutes import EmptyTranscriptError
from vozata.ports import (
    Cancellable,
    Diarizer,
    LlmUnreachableError,
    SessionAudio,
    SessionObserver,
    SessionRepository,
)
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.session_meta import SessionMeta
from vozata.transcription.language_lock import LanguageLock

if TYPE_CHECKING:
    from vozata.session import SessionComponents

_log = logging.getLogger(__name__)


class SessionFinisher:
    """Mix, identify speakers, write minutes and action items, index and mark a session done.

    `title` is read when the minutes are written (a meeting may be renamed while it waits).
    `meta` (the live session's) is updated by `ended`; without it `session.json` is read and
    rewritten, so changes made meanwhile (a rename) are kept.
    """

    def __init__(
        self,
        settings: Settings,
        store: SessionRepository,
        audio: SessionAudio,
        components: SessionComponents,
        observer: SessionObserver,
        session_id: str,
        language: LanguageLock,
        title: Callable[[], str | None],
        meta: SessionMeta | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._audio = audio
        self._c = components
        self._observer = observer
        self._id = session_id
        self._lock = language
        self._title = title
        self._meta = meta

    def close(self) -> None:
        """Close the language model clients this finisher was built with (a per-attempt finisher
        of the processing job, phase 40); the session's own finisher (CLI) is never closed."""
        for model in (self._c.minutes, self._c.action_items):
            if model is not None:
                try:
                    model.close()
                except Exception:
                    _log.exception("Closing a language model client failed")

    def mix(self) -> None:
        try:
            self._audio.write_mix(self._id, self._c.mixer)
        except Exception as error:
            _log.exception("Mixing %s failed", self._id)
            self._error("mix_failed", reason=str(error))

    def identify_speakers(self, token: CancelToken) -> None:
        """Diarize the system track (Whisper is already released); a failure keeps `system`
        labels.

        Once speakers are written, `speakers_relabeled` tells clients to reload the transcript:
        the post-session speakers replace the live ones (phase 15). A cancel stops the diarizer
        and raises `StepCancelled`: nothing is written and no error is reported.
        """
        factory = self._c.diarizer_factory
        if factory is None:
            return
        token.raise_if_cancelled()
        unregister: list[Callable[[], None]] = []

        def cancellable() -> Diarizer:
            diarizer = factory()  # may download its model first (phase 42): a cancel can land
            if isinstance(diarizer, Cancellable):
                unregister.append(token.on_cancel(diarizer.cancel))  # runs now if cancelled
            if token.cancelled:  # never spawn next to the live recording that pre-empted us
                _close_quietly(diarizer)
                raise StepCancelled
            return diarizer

        try:
            found = diarize_session(
                self._store,
                self._audio,
                self._id,
                cancellable,
                self._settings.min_speakers,
                self._settings.max_speakers,
            )
        except Exception as error:
            if token.cancelled:
                raise StepCancelled from error
            _log.warning("Speaker identification for %s failed: %s", self._id, error)
            command = f'python -m vozata diarize "{self._command_target()}"'
            self._error("diarization_failed", reason=self._reason(error), command=command)
            return
        finally:
            for undo in unregister:
                undo()
        if found is not None:
            self._observer.on_speakers_relabeled(self._id)

    def write_minutes(self, token: CancelToken) -> None:
        """The minutes from the best transcript; `minutes_ready` only after they were written."""
        minutes = self._c.minutes
        if minutes is None:
            return
        token.raise_if_cancelled()
        segments = self._store.load_transcript(self._id)
        if not segments:
            _log.info("No speech in %s; minutes skipped", self._id)
            return
        unregister = token.on_cancel(minutes.cancel)
        try:
            labeler = self._c.labeler.with_names(self._store.speaker_names(self._id))
            text = minutes.generate(
                segments, labeler, self._lock.language, self._c.vocabulary, title=self._title()
            )
        except Exception as error:
            if token.cancelled:
                raise StepCancelled from error
            if isinstance(error, LlmUnreachableError):
                self._unreachable("minutes", error)
                return
            _log.exception("Generating minutes for %s failed", self._id)
            command = f'python -m vozata minutes "{self._command_target()}"'
            self._error("minutes_failed", reason=str(error), command=command)
            return
        finally:
            unregister()
        token.raise_if_cancelled()
        self._store.write_minutes(self._id, text + "\n")
        self._observer.on_minutes_ready(self._id)

    def extract_action_items(self, token: CancelToken) -> None:
        """After the minutes, with the same model (phase 23); a failure keeps everything else."""
        extractor = self._c.action_items
        if extractor is None:
            return
        token.raise_if_cancelled()
        unregister = token.on_cancel(extractor.cancel)
        try:
            items = write_session_action_items(self._store, self._id, extractor, self._c.labeler)
        except EmptyTranscriptError:
            return
        except Exception as error:
            if token.cancelled:
                raise StepCancelled from error
            if isinstance(error, LlmUnreachableError):
                self._unreachable("action_items", error)
                return
            _log.exception("Extracting action items for %s failed", self._id)
            self._error("action_items_failed", reason=str(error))
            return
        finally:
            unregister()
        self._observer.on_action_items_ready(self._id, len(items))

    def index(self) -> None:
        if self._c.search_index is None:
            return
        try:
            self._c.search_index.index_session(self._id, self._store.load_transcript(self._id))
        except Exception as error:
            _log.exception("Indexing %s for search failed", self._id)
            self._error("index_failed", reason=str(error))

    def ended(self, at: datetime) -> None:
        """Stamp `ended_at` and the `done` status in `session.json`."""
        stamp = at.isoformat(timespec="seconds")
        if self._meta is not None:
            self._meta.ended(at)
            self._meta.set_status(SessionStatus.DONE)
            return
        meta = self._store.read_meta(self._id)
        meta.update(ended_at=stamp, status=SessionStatus.DONE.value)
        self._store.write_meta(self._id, meta)

    def _command_target(self) -> str:
        """What the CLI commands in error messages take: the session folder, or for a backend
        without folders `OUTPUT_DIR/<id>` (the commands open the storage of its parent)."""
        folder: Path | None = self._store.folder(self._id)
        return str(folder if folder is not None else self._settings.output_dir / self._id)

    def _reason(self, error: Exception) -> str:
        return error.render(self._c.localizer) if isinstance(error, ConfigError) else str(error)

    def _unreachable(self, step: str, error: LlmUnreachableError) -> None:
        """The Ollama PC does not answer: no traceback, one localized line naming its host."""
        _log.warning("The language model is unreachable for %s: %s", self._id, error)
        message = self._c.localizer.t(f"errors.llm_unreachable.{step}", host=error.host)
        self._observer.on_error("llm_unreachable", message)

    def _error(self, code: str, **params: object) -> None:
        self._observer.on_error(code, self._c.localizer.t(f"errors.session.{code}", **params))


def _close_quietly(diarizer: Diarizer) -> None:
    try:
        diarizer.close()
    except Exception:
        _log.exception("Closing a cancelled diarizer failed")
