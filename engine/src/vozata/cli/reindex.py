"""`python -m vozata reindex`: rebuild the search index from every session (phase 22)."""

from __future__ import annotations

import sqlite3
from typing import Protocol

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer, SessionRepository


class RebuildableIndex(Protocol):
    """`SearchIndex` (file backend) or `SqliteSearch` (SQLite backend, phase 31)."""

    def rebuild(self, store: SessionRepository) -> int: ...


def run_reindex(
    store: SessionRepository,
    index: RebuildableIndex,
    console: ConsoleObserver,
    localizer: Localizer,
) -> int:
    """Replace the whole index with each session's best transcript."""
    try:
        count = index.rebuild(store)
    except (sqlite3.Error, OSError) as error:
        console.say(localizer.t("cli.reindex_failed", reason=error))
        return 1
    console.say(localizer.t("cli.reindexed", count=count))
    return 0
