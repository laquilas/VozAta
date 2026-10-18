"""`Database` (phase 31): pragmas, per-thread connections, serialized writes and migrations."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from vozata.storage.sqlite.db import (
    Database,
    DatabaseVersionError,
    Migration,
    bundled_migrations,
    migrate,
    schema_version,
    statements,
)

TABLES = {"sessions", "segments", "translations", "speakers", "minutes", "action_items"}


def _tables(db: sqlite3.Connection) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type IN ('table')").fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def database(tmp_path: Path):
    database = Database(tmp_path / "data" / "vozata.db")
    yield database
    database.close()


def test_a_new_file_gets_the_whole_schema(database: Database) -> None:
    db = database.connection()

    assert database.path.is_file()
    assert schema_version(db) == bundled_migrations()[-1].version
    assert TABLES | {"segments_fts"} <= _tables(db)


def test_the_bundled_migrations_are_numbered_from_one_without_gaps() -> None:
    versions = [migration.version for migration in bundled_migrations()]

    assert versions == list(range(1, len(versions) + 1))
    assert len(versions) >= 2


def test_connections_use_wal_foreign_keys_and_a_busy_timeout(database: Database) -> None:
    db = database.connection()

    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] > 0
    with pytest.raises(sqlite3.IntegrityError), database.write() as write:  # no such session
        write.execute("INSERT INTO speakers (session_id, speaker_id) VALUES ('nope', 'mic')")


def test_a_database_at_the_previous_version_is_migrated_and_keeps_its_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vozata.db"
    *older, latest = bundled_migrations()
    Database(path, older).close()
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("INSERT INTO sessions (id, meta_json) VALUES ('20261015_202358', '{}')")
    db.execute(
        "INSERT INTO segments (session_id, source, segment_id, channel, speaker_id, start,"
        ' "end", text, words_json) VALUES'
        " ('20261015_202358', 'raw', 'mic-000001', 'mic', 'mic', 0, 1, 'Decisão tomada', '[]')"
    )
    db.close()

    database = Database(path)
    try:
        db = database.connection()
        assert schema_version(db) == latest.version
        hits = db.execute("SELECT segment_id FROM segments_fts WHERE segments_fts MATCH 'decisao'")
        assert hits.fetchall() == [("mic-000001",)]  # rows written before the FTS are indexed
    finally:
        database.close()


def test_opening_again_applies_nothing(tmp_path: Path) -> None:
    path = tmp_path / "vozata.db"
    Database(path).close()

    database = Database(path)
    try:
        assert schema_version(database.connection()) == bundled_migrations()[-1].version
    finally:
        database.close()


def test_a_database_from_a_newer_engine_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "vozata.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 999")
    db.close()

    with pytest.raises(DatabaseVersionError):
        Database(path)


def test_a_failing_migration_is_rolled_back(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "vozata.db", isolation_level=None)
    broken = [
        Migration(1, "001_ok.sql", "CREATE TABLE a (x);"),
        Migration(2, "002_bad.sql", "CREATE TABLE b (x);\nNOT SQL;"),
    ]

    with pytest.raises(sqlite3.OperationalError):
        migrate(db, broken)

    assert schema_version(db) == 1
    assert _tables(db) == {"a"}
    db.close()


def test_statements_keep_trigger_bodies_whole() -> None:
    script = (
        "-- a comment\nCREATE TABLE t (x);\n"
        "CREATE TRIGGER g AFTER INSERT ON t BEGIN\n  SELECT 1;\n  SELECT 2;\nEND;\n"
        "SELECT 3\n-- trailing comment\n"
    )

    parts = statements(script)

    assert len(parts) == 3
    assert parts[1].startswith("CREATE TRIGGER") and parts[1].endswith("END;")
    assert parts[2].startswith("SELECT 3")
    assert statements("-- only a comment\n") == []


def test_each_thread_has_its_own_connection(database: Database) -> None:
    mine = database.connection()
    theirs: list[sqlite3.Connection] = []
    thread = threading.Thread(target=lambda: theirs.append(database.connection()))
    thread.start()
    thread.join()

    assert database.connection() is mine
    assert theirs[0] is not mine


def test_a_failed_write_is_rolled_back(database: Database) -> None:
    with pytest.raises(RuntimeError), database.write() as db:
        db.execute("INSERT INTO sessions (id) VALUES ('20261015_202358')")
        raise RuntimeError("boom")

    assert database.connection().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_nested_writes_and_reads_join_the_outer_transaction(database: Database) -> None:
    with database.write() as outer:
        outer.execute("INSERT INTO sessions (id) VALUES ('20261015_202358')")
        with database.write() as inner, database.read() as read:
            assert inner is outer is read
            inner.execute("INSERT INTO sessions (id) VALUES ('20261015_202359')")

    assert database.connection().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


def test_a_durable_write_syncs_fully_then_goes_back_to_normal(database: Database) -> None:
    with database.write(durable=True) as db:
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL

    assert database.connection().execute("PRAGMA synchronous").fetchone()[0] == 1


def test_a_reader_sees_committed_rows_while_another_thread_writes(database: Database) -> None:
    started = threading.Event()
    release = threading.Event()
    with database.write() as db:
        db.execute("INSERT INTO sessions (id) VALUES ('20261015_202358')")

    def writer() -> None:
        with database.write() as db:
            db.execute("INSERT INTO sessions (id) VALUES ('20261015_202359')")
            started.set()
            assert release.wait(5)

    thread = threading.Thread(target=writer)
    thread.start()
    assert started.wait(5)
    try:
        with database.read() as db:  # WAL: not blocked by the open write transaction
            assert db.execute("SELECT id FROM sessions").fetchall() == [("20261015_202358",)]
    finally:
        release.set()
        thread.join()
    rows = database.connection().execute("SELECT COUNT(*) FROM sessions").fetchone()
    assert rows[0] == 2


def test_close_closes_every_connection_and_a_new_one_opens_on_use(database: Database) -> None:
    first = database.connection()

    database.close()

    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")
    assert database.connection().execute("SELECT 1").fetchone() == (1,)
