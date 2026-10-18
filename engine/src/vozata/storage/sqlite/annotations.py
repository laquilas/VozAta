"""Session annotations in `vozata.db`: translations, speakers, minutes and action items."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime

from vozata.domain import ActionItem, Translation
from vozata.ports import TranslationWriter
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.rows import (
    ACTION_ITEM_COLUMNS,
    action_item_row,
    check_id,
    row_action_item,
)
from vozata.storage.sqlite.writers import SqliteTranslationWriter


class SessionAnnotations:
    """The `SessionRepository` methods about what is added to a session's transcript."""

    def __init__(self, database: Database, now: Callable[[], datetime]) -> None:
        self._db = database
        self.now = now
        self._action_items_lock = threading.RLock()

    def open_translations(self, session_id: str) -> TranslationWriter:
        check_id(session_id)
        return SqliteTranslationWriter(self._db, session_id)

    def load_translations(self, session_id: str) -> dict[str, Translation]:
        check_id(session_id)
        rows = self._db.connection().execute(
            "SELECT segment_id, language, text FROM translations WHERE session_id = ?",
            (session_id,),
        )
        return {row[0]: Translation(*row) for row in rows}

    def speaker_names(self, session_id: str) -> dict[str, str]:
        check_id(session_id)
        rows = self._db.connection().execute(
            "SELECT speaker_id, name FROM speakers WHERE session_id = ? AND name IS NOT NULL"
            " ORDER BY rowid",
            (session_id,),
        )
        return dict(rows.fetchall())

    def write_speakers(self, session_id: str, speaker_ids: Sequence[str]) -> None:
        check_id(session_id)
        with self._db.write() as db:
            db.execute("DELETE FROM speakers WHERE session_id = ?", (session_id,))
            db.executemany(
                "INSERT OR IGNORE INTO speakers (session_id, speaker_id) VALUES (?, ?)",
                [(session_id, speaker_id) for speaker_id in speaker_ids],
            )

    def rename_speakers(self, session_id: str, names: Mapping[str, str | None]) -> None:
        check_id(session_id)
        with self._db.write() as db:
            db.executemany(
                "INSERT INTO speakers (session_id, speaker_id, name) VALUES (?, ?, ?)"
                " ON CONFLICT (session_id, speaker_id) DO UPDATE SET name = excluded.name",
                [(session_id, key, (name or "").strip() or None) for key, name in names.items()],
            )

    def speaker_count(self, session_id: str) -> int:
        """Speakers found by diarization (`system:<n>`; renamed `mic` / `system` do not count)."""
        check_id(session_id)
        row = (
            self._db.connection()
            .execute(
                "SELECT COUNT(*) FROM speakers WHERE session_id = ? AND speaker_id LIKE 'system:%'",
                (session_id,),
            )
            .fetchone()
        )
        return int(row[0])

    def read_minutes(self, session_id: str) -> str | None:
        check_id(session_id)
        row = (
            self._db.connection()
            .execute("SELECT markdown FROM minutes WHERE session_id = ?", (session_id,))
            .fetchone()
        )
        return None if row is None else str(row[0])

    def write_minutes(
        self, session_id: str, markdown: str, generated_at: datetime | None = None
    ) -> None:
        """Stored with the session's template and the time it was written (`generated_at`,
        default now: the folder import of phase 33 keeps the original time)."""
        check_id(session_id)
        written = (generated_at or self.now()).isoformat(timespec="seconds")
        with self._db.write() as db:
            db.execute(
                "INSERT INTO minutes (session_id, markdown, template, generated_at)"
                " VALUES (?, ?, (SELECT template FROM sessions WHERE id = ?), ?)"
                " ON CONFLICT (session_id) DO UPDATE SET markdown = excluded.markdown,"
                " template = excluded.template, generated_at = excluded.generated_at",
                (session_id, markdown, session_id, written),
            )

    def has_minutes(self, session_id: str) -> bool:
        return self.read_minutes(session_id) is not None

    def read_action_items(self, session_id: str) -> list[ActionItem]:
        check_id(session_id)
        rows = self._db.connection().execute(
            f"SELECT {ACTION_ITEM_COLUMNS} FROM action_items WHERE session_id = ? ORDER BY row_id",
            (session_id,),
        )
        return [row_action_item(row) for row in rows]

    def write_action_items(self, session_id: str, items: Sequence[ActionItem]) -> None:
        """Replace the items in one transaction."""
        check_id(session_id)
        with self._db.write() as db:
            db.execute("DELETE FROM action_items WHERE session_id = ?", (session_id,))
            db.executemany(
                f"INSERT INTO action_items (session_id, {ACTION_ITEM_COLUMNS})"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(session_id, *action_item_row(item)) for item in items],
            )

    def action_items_lock(self) -> AbstractContextManager[object]:
        return self._action_items_lock
