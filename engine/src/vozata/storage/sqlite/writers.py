"""What a recording appends to `vozata.db`: the live transcript and live translations."""

from __future__ import annotations

from collections.abc import Sequence

from vozata.domain import TranscriptSegment, Translation
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.rows import SEGMENT_COLUMNS, segment_row


def insert_segments(
    database: Database, session_id: str, source: str, segments: Sequence[TranscriptSegment]
) -> None:
    """Insert `segments` of `source` in order (call inside `database.write()`)."""
    database.connection().executemany(
        f"INSERT INTO segments (session_id, source, {SEGMENT_COLUMNS})"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(session_id, source, *segment_row(segment)) for segment in segments],
    )


class SqliteTranscriptSink:
    """The raw transcript of a recording: one committed (`synchronous=FULL`) row per segment,
    so every emitted segment survives a crash."""

    def __init__(self, database: Database, session_id: str) -> None:
        self._database = database
        self._session_id = session_id

    def emit(self, segment: TranscriptSegment) -> None:
        with self._database.write(durable=True):
            insert_segments(self._database, self._session_id, "raw", [segment])

    def close(self) -> None:
        """Nothing to flush: every segment is committed by `emit`."""


class SqliteTranslationWriter:
    """Live translations (phase 29); a new translation of a segment replaces the old one."""

    def __init__(self, database: Database, session_id: str) -> None:
        self._database = database
        self._session_id = session_id

    def append(self, translation: Translation) -> None:
        with self._database.write() as db:
            db.execute(
                "INSERT INTO translations (session_id, segment_id, language, text)"
                " VALUES (?, ?, ?, ?) ON CONFLICT (session_id, segment_id)"
                " DO UPDATE SET language = excluded.language, text = excluded.text",
                (self._session_id, translation.segment_id, translation.language, translation.text),
            )

    def close(self) -> None:
        """Nothing to flush: every translation is committed by `append`."""
