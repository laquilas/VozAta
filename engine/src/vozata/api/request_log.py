"""The request history of each meeting (phase 59): what was asked and what became of it.

Every request made on a meeting — a voice command, or minutes so far / of a range / again, action
items, a question — is an entry kept with the meeting (`SessionRepository.read_requests`). Each
change publishes `request_updated {request}`, which drives the voice status of the sidebar and the
meeting's Histórico tab.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from vozata.api.ws import EventBroadcaster
from vozata.domain import RequestEntry
from vozata.ports import SessionRepository

MAX_ENTRIES = 200  # per meeting; the oldest are dropped
FINISHED = frozenset({"done", "failed", "ignored"})

_log = logging.getLogger(__name__)


class RequestLog:
    """Thread-safe: jobs finish their entries from their own threads. Storage failures are logged
    and never break the request itself."""

    def __init__(
        self,
        store: SessionRepository,
        broadcaster: EventBroadcaster,
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    ) -> None:
        self._store = store
        self._broadcaster = broadcaster
        self._now = now
        self._new_id = new_id
        self._lock = threading.Lock()

    def begin(
        self,
        session_id: str,
        kind: str,
        source: str,
        *,
        text: str = "",
        at: float | None = None,
        status: str = "running",
        result_id: str | None = None,
        message: str | None = None,
    ) -> str:
        """A new entry; its id."""
        created = self._now().isoformat(timespec="seconds")
        entry = RequestEntry(
            self._new_id(),
            created,
            None if at is None else round(at, 1),
            kind,
            source,
            text,
            status,
            result_id,
            message,
            created if status in FINISHED else None,
        )
        with self._lock:
            self._save(session_id, lambda items: [*items, entry][-MAX_ENTRIES:])
        self._publish(session_id, entry)
        return entry.id

    def update(
        self,
        session_id: str,
        request_id: str,
        status: str,
        *,
        result_id: str | None = None,
        message: str | None = None,
    ) -> None:
        self._change(session_id, lambda entry: entry.id == request_id, status, result_id, message)

    def finish_pending(
        self,
        session_id: str,
        kinds: frozenset[str],
        status: str,
        *,
        result_id: str | None = None,
        message: str | None = None,
    ) -> None:
        """Finish the latest unfinished entry of one of `kinds` (a job finishing its work)."""
        self._change(
            session_id,
            lambda entry: entry.kind in kinds and entry.status not in FINISHED,
            status,
            result_id,
            message,
        )

    def finish_result(
        self, session_id: str, result_id: str, status: str, *, message: str | None = None
    ) -> None:
        """Finish the unfinished entry waiting for `result_id` (an answer)."""
        self._change(
            session_id,
            lambda entry: entry.result_id == result_id and entry.status not in FINISHED,
            status,
            None,
            message,
        )

    def _change(
        self,
        session_id: str,
        match: Callable[[RequestEntry], bool],
        status: str,
        result_id: str | None,
        message: str | None,
    ) -> None:
        changed: list[RequestEntry] = []

        def apply(items: list[RequestEntry]) -> list[RequestEntry]:
            for index in range(len(items) - 1, -1, -1):
                entry = items[index]
                if match(entry):
                    finished = self._now().isoformat(timespec="seconds")
                    updated = replace(
                        entry,
                        status=status,
                        result_id=result_id or entry.result_id,
                        message=message,
                        finished_at=finished if status in FINISHED else None,
                    )
                    changed.append(updated)
                    return [*items[:index], updated, *items[index + 1 :]]
            return items

        with self._lock:
            self._save(session_id, apply)
        for entry in changed:
            self._publish(session_id, entry)

    def _save(
        self, session_id: str, change: Callable[[list[RequestEntry]], list[RequestEntry]]
    ) -> None:
        try:
            items = self._store.read_requests(session_id)
            updated = change(items)
            if updated is not items:
                self._store.write_requests(session_id, updated)
        except Exception:
            _log.exception("The request history of %s could not be saved", session_id)

    def _publish(self, session_id: str, entry: RequestEntry) -> None:
        self._broadcaster.publish("request_updated", session_id, {"request": entry.to_dict()})


def record(
    log: RequestLog | None,
    session_id: str,
    kind: str,
    source: str,
    *,
    text: str = "",
    result_id: str | None = None,
) -> str | None:
    """`begin` on an optional log (a route about to start a job); the id or None."""
    if log is None:
        return None
    return log.begin(session_id, kind, source, text=text, result_id=result_id)


def refused(log: RequestLog | None, session_id: str, request_id: str | None, code: str) -> None:
    """The job did not start (already running / queued): the entry is `ignored` with `code`."""
    if log is not None and request_id is not None:
        log.update(session_id, request_id, "ignored", message=code)
