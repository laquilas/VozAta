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

TABLES = {
    "sessions",
    "segments",
    "translations",
    "speakers",
    "minutes",
    "action_items",
    "audio_chunks",
}


def _tables(db: sqlite3.Connection) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type IN ('table')").fetchall()
    return {row[0] for row in rows}


@pytest.fixture
def database(tmp_path: Path):
    database = Database(tmp_path / "data" / "vozata.db")
    yield database
    database.close()


def test_nothing_is_created_before_the_first_connection(database: Database) -> None:
    assert not database.path.parent.exists()


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
    previous = Database(path, older)
    assert schema_version(previous.connection()) == latest.version - 1
    previous.close()
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


def test_a_new_file_reclaims_free_pages_incrementally(database: Database) -> None:
    db = database.connection()

    assert db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL


def test_an_older_file_without_auto_vacuum_is_converted_once_and_keeps_its_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vozata.db"
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA journal_mode = WAL")
    for migration in bundled_migrations()[:2]:  # a phase 31 database
        for statement in statements(migration.script):
            db.execute(statement)
    db.execute("PRAGMA user_version = 2")
    db.execute("INSERT INTO sessions (id, meta_json) VALUES ('20261015_202358', '{}')")
    assert db.execute("PRAGMA auto_vacuum").fetchone()[0] == 0
    db.close()

    database = Database(path)
    try:
        db = database.connection()
        assert db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        assert db.execute("SELECT id FROM sessions").fetchall() == [("20261015_202358",)]
    finally:
        database.close()


def test_reclaim_gives_free_pages_back_to_the_file_system(database: Database) -> None:
    with database.write() as db:
        db.execute("INSERT INTO sessions (id) VALUES ('s')")
        db.executemany(
            "INSERT INTO audio_chunks VALUES ('s', 'mic', ?, ?, 4000, ?)",
            [(seq, seq * 4000, bytes(8000)) for seq in range(200)],
        )
    with database.write() as db:
        db.execute("DELETE FROM sessions")
    db = database.connection()
    assert db.execute("PRAGMA freelist_count").fetchone()[0] > 0

    database.reclaim()

    assert db.execute("PRAGMA freelist_count").fetchone()[0] == 0


def test_opening_again_applies_nothing(tmp_path: Path) -> None:
    path = tmp_path / "vozata.db"
    first = Database(path)
    first.connection()
    first.close()

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

    database = Database(path)
    try:
        with pytest.raises(DatabaseVersionError):
            database.connection()
        with pytest.raises(DatabaseVersionError):  # every use, not only the first one
            database.connection()
    finally:
        database.close()


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


def test_the_connection_of_a_finished_thread_is_closed_by_the_next_new_one(
    database: Database,
) -> None:
    theirs: list[sqlite3.Connection] = []
    thread = threading.Thread(target=lambda: theirs.append(database.connection()))
    thread.start()
    thread.join()
    theirs[0].execute("SELECT 1")  # still open: nobody has opened a connection since

    database.connection()  # this thread's first one

    with pytest.raises(sqlite3.ProgrammingError):
        theirs[0].execute("SELECT 1")


def test_opening_retries_while_a_crashed_writer_still_holds_the_file(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    connect = database._connect
    failures = [sqlite3.OperationalError("disk I/O error")] * 2

    def flaky() -> sqlite3.Connection:
        if failures:
            raise failures.pop()
        return connect()

    monkeypatch.setattr(database, "_connect", flaky)
    monkeypatch.setattr("vozata.storage.sqlite.db.OPEN_RETRY_SECONDS", 0)

    assert database.connection().execute("SELECT 1").fetchone() == (1,)
    assert failures == []


def test_opening_gives_up_after_the_last_attempt(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(database, "_connect", broken)
    monkeypatch.setattr("vozata.storage.sqlite.db.OPEN_RETRY_SECONDS", 0)

    with pytest.raises(sqlite3.OperationalError):
        database.connection()


def test_a_connection_whose_setup_fails_is_closed(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[sqlite3.Connection] = []
    real = sqlite3.connect

    class Failing:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self.inner = inner
            opened.append(inner)

        def execute(self, sql: str) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        def close(self) -> None:
            self.inner.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: Failing(real(*a, **k)))
    database.path.parent.mkdir(parents=True)

    with pytest.raises(sqlite3.OperationalError):
        database._connect()

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


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
