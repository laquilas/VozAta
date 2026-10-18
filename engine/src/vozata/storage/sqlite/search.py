"""`SqliteSearch`: the `TranscriptSearch` port over `segments_fts` in `vozata.db` (phase 31).

The triggers of `002_search.sql` keep the index in sync with each session's best transcript, so
nothing has to be indexed by hand; `rebuild` (`python -m vozata reindex`) builds it again from
the segment rows. No `index.db` is created.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from vozata.domain import SearchHit, TranscriptSegment
from vozata.ports import SessionRepository
from vozata.storage.search_index import fts_query, search_table
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.rows import SOURCE_RANK

_REBUILD = f"""
INSERT INTO segments_fts (rowid, session_id, segment_id, start, speaker_id, text)
SELECT row_id, session_id, segment_id, start, speaker_id, text FROM segments AS kept
WHERE {SOURCE_RANK} = (
    SELECT MAX({SOURCE_RANK}) FROM segments WHERE session_id = kept.session_id
)
"""

_log = logging.getLogger(__name__)


class SqliteSearch:
    """Full-text search of the SQLite backend."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        """Nothing to do: the stored transcript is indexed by the database triggers as written
        (callers pass the session's best transcript, which is already there)."""

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        match = fts_query(query)
        if match is None:
            return []
        with self._db.read() as db:
            return search_table(db, "segments_fts", match, limit)

    def rebuild(self, store: SessionRepository) -> int:
        """Rebuild `segments_fts` from the best transcript of every session; returns how many
        sessions are listed."""
        with self._db.write() as db:
            db.execute("DELETE FROM segments_fts")
            db.execute(_REBUILD)
        count = len(store.list_sessions())
        _log.info("Search index rebuilt: %d sessions", count)
        return count

    def ensure(self, store: SessionRepository) -> None:
        """Nothing to do: the index is part of the database (the file backend builds `index.db`
        here on the first run after an upgrade)."""
