"""The engine's side of the recorder process (phase 61): attach, follow, rebuild.

Every second `tick()` looks at the recordings under `live/`:

- the recording the current session follows: its pause / resume / stop are applied to the
  session (the manifest is the truth; when it stopped, the session ends at its length);
- a recording no session follows yet, when the recording slot is free: a session is attached to
  it. It replays the recording from the first frame (live transcription as the recording asked
  for), so what was said before the engine came up is transcribed too; a recording that already
  stopped is replayed audio only, at disk speed, and transcribed after Stop by the queue;
- a recording a dead engine was following (`engine.json` names a session still `recording`):
  that partial session is discarded and rebuilt from the files, which hold every sample until
  the `ingest` step checked the store; its title is carried over.

The engine never writes `recording.json` (the recorder rewrites it from memory): it keeps its
link to the recording in `live/<id>/engine.json`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from vozata.api.session_manager import (
    NoActiveSessionError,
    SessionConflictError,
    StartOptions,
)
from vozata.domain import ConversationLanguage, SessionStatus, TranslationTarget
from vozata.ports import SessionRepository
from vozata.recorder.attach import RecordingAttach
from vozata.recorder.engine_link import read_link, write_link
from vozata.recorder.manifest import (
    PAUSED,
    RECORDING,
    Manifest,
    list_recordings,
    live_dir,
    read_manifest,
)
from vozata.recorder_client import RecorderApiError, RecorderUnavailableError
from vozata.session_title import TitleTooLongError, normalize_title

_log = logging.getLogger(__name__)

TICK_SECONDS = 1.0
_PARTIAL = {SessionStatus.RECORDING.value, SessionStatus.PAUSED.value, "interrupted"}


class Manager(Protocol):
    @property
    def current(self) -> Any: ...

    def start(self, options: StartOptions) -> dict[str, Any]: ...

    def pause(self) -> dict[str, Any]: ...

    def resume(self) -> dict[str, Any]: ...

    def stop(self) -> dict[str, Any]: ...

    def delete(self, session_id: str) -> None: ...

    def summary(self, session: Any) -> dict[str, Any]: ...


class Recorder(Protocol):
    def health(self) -> dict[str, Any] | None: ...

    def start(self, body: dict[str, Any]) -> dict[str, Any]: ...

    def pause(self) -> dict[str, Any]: ...

    def resume(self) -> dict[str, Any]: ...

    def stop(self) -> dict[str, Any]: ...

    def update_options(self, options: dict[str, Any]) -> dict[str, Any]: ...


def start_options(options: dict[str, Any], live: bool) -> StartOptions:
    """The session options of a recording; a bad value falls back to the default, never fails
    (the audio must be processed whatever the options say)."""

    def choice(enum: Any, key: str) -> Any:
        try:
            return enum(options[key]) if options.get(key) else None
        except ValueError:
            return None

    try:
        title = (
            normalize_title(options.get("title")) if isinstance(options.get("title"), str) else None
        )
    except TitleTooLongError:
        title = None
    terms = options.get("vocabulary")
    vocabulary = tuple(t for t in terms if isinstance(t, str)) if isinstance(terms, list) else ()
    template = options.get("template")
    wants_live = options.get("live_transcription")
    return StartOptions(
        language=choice(ConversationLanguage, "language"),
        template=template if isinstance(template, str) and template else None,
        vocabulary=vocabulary,
        translate_to=choice(TranslationTarget, "translate_to"),
        title=title,
        live_transcription=(wants_live if isinstance(wants_live, bool) else None)
        if live
        else False,
    )


class RecorderLink:
    def __init__(
        self,
        output_dir: Path,
        manager: Manager,
        store: SessionRepository,
        recorder: Recorder,
        check_template: Callable[[str], bool] = lambda template: True,
        cleanup: Callable[[str], object] = lambda session_id: None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        self._output_dir = output_dir
        self._manager = manager
        self._store = store
        self._recorder = recorder
        self._check_template = check_template
        self._cleanup = cleanup
        self._wall = wall_clock
        self._tick_seconds = tick_seconds
        self._lock = threading.RLock()
        self._stopping: str | None = None  # the recording whose stop was handed to the manager
        self._skipped: set[str] = set()  # logged once: a link to a meeting that no longer exists
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def live(self) -> Path:
        return live_dir(self._output_dir)

    # -- background ---------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="recorder-link", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._closed.wait(self._tick_seconds):
            try:
                self.tick()
            except Exception:
                _log.exception("Following the recorder failed")

    # -- what the API asks --------------------------------------------------------------------

    def following(self) -> str | None:
        """The recording the current session follows, or None."""
        session = self._manager.current
        return getattr(session, "recorder_id", None) if session is not None else None

    def linked_sessions(self) -> set[str]:
        """Sessions linked to a recording still under `live/` (never offered for recovery: they
        are rebuilt from the recording)."""
        linked = set()
        for recording_id in list_recordings(self._output_dir):
            session_id = read_link(self.live / recording_id)
            if session_id is not None:
                linked.add(session_id)
        return linked

    def recorder_available(self) -> bool:
        return self._recorder.health() is not None

    def recorder_health(self) -> dict[str, Any] | None:
        """The recorder's `/health`, or None when it does not answer."""
        return self._recorder.health()

    def start_recording(self, body: dict[str, Any]) -> dict[str, Any]:
        """`POST /sessions` with the recorder: it records, the engine attaches at once."""
        devices = {k: body.pop(k) for k in ("mic_device_id", "system_device_id") if k in body}
        summary = self._recorder.start({**devices, "options": body})
        with self._lock:
            self.tick()
        session = self._manager.current
        if session is None or getattr(session, "recorder_id", None) != summary.get("id"):
            raise SessionConflictError  # another meeting holds the slot: the recorder records
        return self._manager.summary(session)

    def pause(self) -> None:
        self._recorder.pause()
        self.tick()

    def resume(self) -> None:
        self._recorder.resume()
        self.tick()

    def stop(self) -> None:
        self._recorder.stop()
        self.tick()

    def mirror_title(self, title: str | None) -> None:
        """Keep the recording's options in step with a rename (a rebuild carries them over)."""
        self.mirror_options({"title": title})

    def mirror_options(self, options: dict[str, Any]) -> None:
        """Keep the recording's options in step with changes made during it (phase 63)."""
        try:
            self._recorder.update_options(options)
        except (RecorderUnavailableError, RecorderApiError):
            _log.info("The recorder did not take the new options")

    # -- the work -----------------------------------------------------------------------------

    def tick(self) -> None:
        with self._lock:
            for recording_id in list_recordings(self._output_dir):
                folder = self.live / recording_id
                try:
                    manifest = read_manifest(folder)
                except (OSError, ValueError):
                    continue  # being replaced, or broken: the next tick tries again
                if self.following() == recording_id:
                    self._follow(manifest)
                elif self._manager.current is None:
                    self._consider(folder, manifest)

    def _follow(self, manifest: Manifest) -> None:
        session = self._manager.current
        status = getattr(session, "status", None)
        try:
            if manifest.active:
                self._stopping = None
                if manifest.status == PAUSED and status is SessionStatus.RECORDING:
                    self._manager.pause()
                elif manifest.status == RECORDING and status is SessionStatus.PAUSED:
                    self._manager.resume()
            elif self._stopping != manifest.id:
                self._stopping = manifest.id
                session.end_at(manifest.duration_seconds)
                self._manager.stop()
        except NoActiveSessionError:
            pass  # a stop is already under way

    def _consider(self, folder: Path, manifest: Manifest) -> None:
        linked = read_link(folder)
        title = None
        if linked is not None:
            meta = self._meta(linked)
            if meta is None:
                if manifest.id not in self._skipped:
                    _log.info(
                        "Recording %s: its meeting %s is gone; left alone", manifest.id, linked
                    )
                    self._skipped.add(manifest.id)
                return
            if meta.get("status") == SessionStatus.DONE.value:
                self._cleanup(linked)  # its `ingest` step could not remove the folder: again
                return
            if meta.get("status") not in _PARTIAL or meta.get("capture_ended_at"):
                return  # stored: the queue processes it, its `ingest` step clears the folder
            title = meta.get("title")
            _log.warning("Rebuilding meeting %s from recording %s", linked, manifest.id)
            try:
                self._manager.delete(linked)
            except Exception:
                _log.exception("Discarding the partial meeting %s failed", linked)
                return
        self._attach(folder, manifest, title)

    def _attach(self, folder: Path, manifest: Manifest, title: str | None) -> None:
        options = start_options(dict(manifest.options), live=manifest.active)
        if options.template is not None and not self._check_template(options.template):
            options = StartOptions(**{**options.__dict__, "template": None})
        if title is not None and options.title is None:
            options = StartOptions(**{**options.__dict__, "title": title})
        attach = RecordingAttach.of(folder, manifest)
        try:
            self._manager.start(StartOptions(**{**options.__dict__, "attach": attach}))
        except SessionConflictError:
            return  # the slot was taken meanwhile; the next tick tries again
        session = self._manager.current
        write_link(folder, session.id, self._wall())
        _log.info("Following recording %s as meeting %s", manifest.id, session.id)
        if not manifest.active:
            self._follow(manifest)  # stopped already: replay it all, then hand it to the queue

    def _meta(self, session_id: str) -> dict[str, Any] | None:
        try:
            return self._store.read_meta(session_id)
        except (OSError, ValueError, LookupError, KeyError):
            return None
