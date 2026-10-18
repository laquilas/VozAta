"""`SqliteSessionRepository`: the `SessionRepository` port over `vozata.db` (phase 31).

Sessions, transcripts, speakers, translations, minutes and action items are rows of one database
(architecture §8). The audio stays in WAV files in `OUTPUT_DIR/<id>/` until phase 32, so `create`
also makes that folder and `discard` removes it; nothing else is written there.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionNotFoundError, TranscriptSink
from vozata.storage.session_range import newest_in_range
from vozata.storage.sqlite.annotations import SessionAnnotations
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.rows import (
    META_COLUMNS,
    SEGMENT_COLUMNS,
    SOURCE_RANK,
    check_id,
    meta_to_row,
    row_segment,
    row_to_meta,
)
from vozata.storage.sqlite.writers import SqliteTranscriptSink, insert_segments


def _local_now() -> datetime:
    return datetime.now().astimezone()


class SqliteSessionRepository(SessionAnnotations):
    """`SessionRepository` of the SQLite backend (annotations: `SessionAnnotations`)."""

    def __init__(
        self, database: Database, output_dir: Path, now: Callable[[], datetime] = _local_now
    ) -> None:
        super().__init__(database, now)
        self._root = output_dir

    @property
    def database(self) -> Database:
        return self._db

    def create(self, started_at: datetime | None = None) -> str:
        """A new session row and its (audio) folder, named after the start time; ids already
        used by a row or a folder (file-backend sessions) are skipped."""
        base = (started_at or self.now()).strftime("%Y%m%d_%H%M%S")
        self._root.mkdir(parents=True, exist_ok=True)
        suffix = 1
        while True:
            session_id = base if suffix == 1 else f"{base}_{suffix}"
            suffix += 1
            try:
                (self._root / session_id).mkdir()
            except FileExistsError:
                continue
            with self._db.write() as db:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,)
                ).rowcount
            if inserted:
                return session_id
            (self._root / session_id).rmdir()

    def discard(self, session_id: str) -> None:
        self._check(session_id)
        with self._db.write() as db:
            db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))  # cascades
        shutil.rmtree(self._root / session_id, ignore_errors=True)

    def read_meta(self, session_id: str) -> dict[str, Any]:
        self._check(session_id)
        row = (
            self._db.connection()
            .execute(
                f"SELECT {', '.join(META_COLUMNS)}, meta_json FROM sessions WHERE id = ?",
                (session_id,),
            )
            .fetchone()
        )
        if row is None or row[-1] is None:
            raise SessionNotFoundError(session_id)
        return row_to_meta(row[:-1], row[-1])

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        """One statement (an UPSERT of the session row): atomic by construction."""
        self._check(session_id)
        columns, meta_json = meta_to_row(meta)
        names = ", ".join(META_COLUMNS)
        updates = ", ".join(f"{name} = excluded.{name}" for name in (*META_COLUMNS, "meta_json"))
        with self._db.write() as db:
            db.execute(
                f"INSERT INTO sessions (id, {names}, meta_json)"
                f" VALUES ({', '.join('?' * (len(META_COLUMNS) + 2))})"
                f" ON CONFLICT (id) DO UPDATE SET {updates}",
                (session_id, *columns, meta_json),
            )

    def list_sessions(self) -> list[str]:
        rows = self._db.connection().execute(
            "SELECT id FROM sessions WHERE meta_json IS NOT NULL ORDER BY id DESC"
        )
        return [row[0] for row in rows]

    def list_range(self, start: datetime, end: datetime) -> list[str]:
        rows = self._db.connection().execute(
            "SELECT id, started_at FROM sessions WHERE meta_json IS NOT NULL"
        )
        return newest_in_range(rows.fetchall(), start, end)

    def delete(self, session_id: str) -> None:
        """Delete the session permanently: its rows (cascade) and its audio folder (phase 36)."""
        self._check(session_id)
        with self._db.write() as db:
            deleted = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount
        if not deleted:
            raise SessionNotFoundError(session_id)
        shutil.rmtree(self._root / session_id, ignore_errors=True)

    def open_transcript(self, session_id: str, labeler: SpeakerLabeler) -> TranscriptSink:
        """Segment rows committed one by one (`labeler` is not needed: no `transcript.md`)."""
        self._check(session_id)
        return SqliteTranscriptSink(self._db, session_id)

    def load_transcript(self, session_id: str) -> list[TranscriptSegment]:
        return self.load_transcript_with_source(session_id)[1]

    def load_transcript_with_source(self, session_id: str) -> tuple[str, list[TranscriptSegment]]:
        self._check(session_id)
        with self._db.read() as db:
            best = db.execute(
                "SELECT source FROM segments WHERE session_id = ?"
                f" ORDER BY {SOURCE_RANK} DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if best is None:
                if db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                    return "raw", []
                raise SessionNotFoundError(session_id)
            return best[0], self._segments(session_id, best[0])

    def load_raw_transcript(self, session_id: str) -> list[TranscriptSegment]:
        self._check(session_id)
        return self._segments(session_id, "raw")

    def write_diarized(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        self._replace_segments(session_id, "diarized", segments)

    def write_edited(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        self._replace_segments(session_id, "edited", segments)

    def delete_edited(self, session_id: str) -> bool:
        self._check(session_id)
        with self._db.write() as db:
            deleted = db.execute(
                "DELETE FROM segments WHERE session_id = ? AND source = 'edited'", (session_id,)
            ).rowcount
        return deleted > 0

    def folder(self, session_id: str) -> Path | None:
        """The folder holding the session's WAVs (audio stays in files until phase 32)."""
        self._check(session_id)
        return self._root / session_id

    def files(self, session_id: str) -> list[str] | None:
        """The audio files of the session (no JSON or Markdown is written next to them)."""
        root = self._root / session_id
        self._check(session_id)
        if not root.is_dir():
            return []
        return sorted(item.name for item in root.iterdir() if item.is_file())

    def _segments(self, session_id: str, source: str) -> list[TranscriptSegment]:
        rows = self._db.connection().execute(
            f"SELECT {SEGMENT_COLUMNS} FROM segments WHERE session_id = ? AND source = ?"
            " ORDER BY row_id",
            (session_id, source),
        )
        return [row_segment(row) for row in rows]

    def _replace_segments(
        self, session_id: str, source: str, segments: Sequence[TranscriptSegment]
    ) -> None:
        self._check(session_id)
        with self._db.write() as db:
            db.execute(
                "DELETE FROM segments WHERE session_id = ? AND source = ?", (session_id, source)
            )
            insert_segments(self._db, session_id, source, segments)

    _check = staticmethod(check_id)
