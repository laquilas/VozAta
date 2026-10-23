"""How a fallback from the VozAta worker to this PC is told (phase 44)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from vozata.ports import Localizer, SessionObserver

FALLBACK = "worker_fallback"

_log = logging.getLogger(__name__)


def fallback_message(localizer: Localizer, task: str, host: str) -> str:
    return localizer.t("errors.worker.fallback", task=localizer.t(f"worker.task.{task}"), host=host)


class ObserverNotices:
    """An `error` event (API) or a console line (CLI) with the code `worker_fallback`;
    `before` runs first, e.g. a live recording taking the GPU gate for the local model."""

    def __init__(
        self,
        observer: SessionObserver,
        localizer: Localizer,
        before: Callable[[str], None] | None = None,
    ) -> None:
        self._observer = observer
        self._localizer = localizer
        self._before = before

    def fallback(self, task: str, host: str) -> None:
        _log.warning("The VozAta worker at %s did not answer: %s runs on this PC", host, task)
        if self._before is not None:
            self._before(task)
        self._observer.on_error(FALLBACK, fallback_message(self._localizer, task, host))


class LoggedNotices:
    """Only a log line: for callers with nobody to tell."""

    def fallback(self, task: str, host: str) -> None:
        _log.warning("The VozAta worker at %s did not answer: %s runs on this PC", host, task)
