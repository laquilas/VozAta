"""`OUTPUT_DIR/index.db`: SQLite FTS5 full-text index of every transcript (phase 22).

Accent- and case-insensitive (`unicode61 remove_diacritics 2`), so `decisao` finds `decisão`.
Each call opens its own connection, so the index is safe to use from any thread.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

from vozata.domain import SNIPPET_END, SNIPPET_START, SearchHit, TranscriptSegment
from vozata.ports import SessionRepository

SNIPPET_TOKENS = 16  # words around the match in a snippet
_ELLIPSIS = "…"
_WORD = re.compile(r"\w+")
_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS segments USING fts5(
    session_id UNINDEXED,
    segment_id UNINDEXED,
    start UNINDEXED,
    speaker_id UNINDEXED,
    text,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""

_log = logging.getLogger(__name__)


def fts_query(text: str) -> str | None:
    """User text as a safe FTS5 query: every word quoted (AND), the last one a prefix.

    Quoting turns FTS syntax (`OR`, `NEAR`, `*`, `:`, parentheses) into plain words; `None` when
    the text has no word at all.
    """
    terms = [f'"{term}"' for term in _WORD.findall(text)]
    if not terms:
        return None
    terms[-1] += "*"
    return " ".join(terms)


class SearchIndex:
    """The `TranscriptSearch` port over an SQLite FTS5 table `segments`."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path

    def exists(self) -> bool:
        return self._path.is_file()

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        with self._connect() as db:
            _replace(db, session_id, segments)

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        match = fts_query(query)
        if match is None:
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT session_id, segment_id, start, speaker_id,"
                " snippet(segments, 4, ?, ?, ?, ?)"
                " FROM segments WHERE segments MATCH ? ORDER BY rank LIMIT ?",
                (SNIPPET_START, SNIPPET_END, _ELLIPSIS, SNIPPET_TOKENS, match, limit),
            ).fetchall()
        return [SearchHit(str(a), str(b), float(c), str(d), str(e)) for a, b, c, d, e in rows]

    def rebuild(self, store: SessionRepository) -> int:
        """Re-index every session from its best transcript; returns how many were indexed."""
        sessions = store.list_sessions()
        with self._connect() as db:
            db.execute("DELETE FROM segments")
            for session_id in sessions:
                _replace(db, session_id, store.load_transcript(session_id))
        _log.info("Search index rebuilt: %d sessions", len(sessions))
        return len(sessions)

    def ensure(self, store: SessionRepository) -> None:
        """First run after an upgrade: rebuild when sessions exist but `index.db` does not.

        Meant for a background thread at startup, so failures are logged, never raised.
        """
        if self.exists() or not store.list_sessions():
            return
        try:
            self.rebuild(store)
        except Exception:
            _log.exception("Building the search index failed")

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=10)
        try:
            with db:  # one transaction: commit on success, roll back on error
                db.execute(_SCHEMA)
                yield db
        finally:
            db.close()


def _replace(
    db: sqlite3.Connection, session_id: str, segments: Sequence[TranscriptSegment]
) -> None:
    db.execute("DELETE FROM segments WHERE session_id = ?", (session_id,))
    db.executemany(
        "INSERT INTO segments (session_id, segment_id, start, speaker_id, text)"
        " VALUES (?, ?, ?, ?, ?)",
        [(session_id, s.segment_id, s.start, s.speaker_id, s.text) for s in segments],
    )
