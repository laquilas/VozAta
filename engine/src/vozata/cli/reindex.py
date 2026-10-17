"""`python -m vozata reindex`: rebuild the search index from every session (phase 22)."""

from __future__ import annotations

import sqlite3

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer, SessionRepository
from vozata.storage.search_index import SearchIndex


def run_reindex(
    store: SessionRepository, index: SearchIndex, console: ConsoleObserver, localizer: Localizer
) -> int:
    """Replace the whole index with each session's best transcript."""
    try:
        count = index.rebuild(store)
    except (sqlite3.Error, OSError) as error:
        console.say(localizer.t("cli.reindex_failed", reason=error))
        return 1
    console.say(localizer.t("cli.reindexed", count=count))
    return 0
