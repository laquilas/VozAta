"""The folder import of phase 33 as a background job of `serve`, reported through events.

At start the job imports the pending folders one at a time (`FolderImporter`), waiting between
folders while a session records, pauses, finalizes or is recovered (one heavy job at a time).
Each step publishes `migration_progress {done, total, current, paused}`; the end publishes
`migration_done {state, imported, skipped, errors}`. `summary()` is `GET /migration`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from vozata.api.ws import EventBroadcaster
from vozata.ports import Localizer
from vozata.storage.migration import MigrationError, NotEnoughSpaceError

POLL_SECONDS = 1.0  # how often a paused import checks whether the session ended

_log = logging.getLogger(__name__)


class Importer(Protocol):
    def pending(self) -> list[str]: ...

    def import_one(self, session_id: str) -> MigrationError | None: ...

    def errors(self) -> list[MigrationError]: ...


class MigrationJob:
    """States: `idle` (not started), `running`, `done`, `no_space` (stopped), `failed`."""

    def __init__(
        self,
        importer: Importer,
        broadcaster: EventBroadcaster,
        localizer: Localizer,
        should_pause: Callable[[], bool] = lambda: False,
        on_done: Callable[[], None] = lambda: None,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        self._importer = importer
        self._broadcaster = broadcaster
        self._t = localizer.t
        self._should_pause = should_pause
        self._on_done = on_done
        self._wait = wait
        self._lock = threading.Lock()
        self._state = "idle"
        self._done = self._total = self._imported = self._skipped = 0
        self._current: str | None = None
        self._paused = False
        self._space: NotEnoughSpaceError | None = None  # why it stopped for space
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="migration", daemon=True)
        self._thread.start()

    def wait_done(self, timeout: float | None = None) -> bool:
        """Block until the job finished (tests, shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def run(self) -> None:
        try:
            pending = self._importer.pending()
            with self._lock:
                self._state, self._total = "running", len(pending)
            for session_id in pending:
                self._wait_while_busy(session_id)
                self._step(session_id)
            self._finish("done")
        except NotEnoughSpaceError as error:
            _log.warning("Folder import stopped: %s", error)
            with self._lock:
                self._space = error
            self._finish("no_space")
        except Exception:
            _log.exception("Importing the session folders failed")
            self._finish("failed")

    def is_running(self) -> bool:
        with self._lock:
            return self._state == "running"

    def progress_message(self) -> dict[str, Any]:
        with self._lock:
            data = self._progress()
        return {"type": "migration_progress", "session_id": None, "data": data}

    def summary(self) -> dict[str, Any]:
        """`GET /migration`: the state, the progress and every folder that was not imported."""
        with self._lock:
            summary = {
                "state": self._state,
                **self._progress(),
                "imported": self._imported,
                "skipped": self._skipped,
                "needed_bytes": self._space.needed if self._space else None,
                "free_bytes": self._space.free if self._space else None,
                "message": self._space_message(),
            }
        summary["errors"] = [
            {"folder": e.folder, "reason": e.reason, "message": self._t(f"migration.{e.reason}")}
            | {"detail": e.detail}
            for e in self._importer.errors()
        ]
        return summary

    def _space_message(self) -> str | None:
        space = self._space
        if space is None:
            return None
        mb = 1024 * 1024
        return self._t(
            "migration.no_space",
            folder=space.folder,
            needed=-(-space.needed // mb),
            free=space.free // mb,
        )

    def _progress(self) -> dict[str, Any]:
        return {
            "done": self._done,
            "total": self._total,
            "current": self._current,
            "paused": self._paused,
        }

    def _wait_while_busy(self, session_id: str) -> None:
        with self._lock:
            self._current = session_id
        while self._should_pause():
            if not self._paused:
                with self._lock:
                    self._paused = True
                self._publish_progress()
            self._wait(POLL_SECONDS)
        if self._paused:
            with self._lock:
                self._paused = False
        self._publish_progress()

    def _step(self, session_id: str) -> None:
        error = self._importer.import_one(session_id)
        if error is not None:
            _log.warning("Not imported: %s (%s: %s)", error.folder, error.reason, error.detail)
        with self._lock:
            self._done += 1
            if error is None:
                self._imported += 1
            else:
                self._skipped += 1

    def _publish_progress(self) -> None:
        message = self.progress_message()
        self._broadcaster.publish(message["type"], None, message["data"])

    def _finish(self, state: str) -> None:
        with self._lock:
            self._state, self._current, self._paused = state, None, False
            data = {"state": state, "imported": self._imported, "skipped": self._skipped}
        data["errors"] = len(self._importer.errors())
        self._broadcaster.publish("migration_done", None, data)
        if self._imported:
            _log.info("Imported %d session folder(s) into the database", self._imported)
        try:
            self._on_done()
        except Exception:
            _log.exception("After the folder import")
