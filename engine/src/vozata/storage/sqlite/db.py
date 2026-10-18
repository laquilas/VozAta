"""`Database`: the connection side of `vozata.db` (phase 31).

Every connection runs in WAL mode with `synchronous=NORMAL`, foreign keys on and a busy timeout.
Each thread gets its own connection (`threading.local`); writes are serialized by one lock and
run in `BEGIN IMMEDIATE` transactions. The schema is migrated on open by `PRAGMA user_version`
from the numbered scripts in `storage/sqlite/migrations/` (`NNN_name.sql`).

The file uses `auto_vacuum=INCREMENTAL` (phase 32): deleted audio leaves free pages that
`reclaim()` gives back to the file system. A file created before that is converted once on open.
"""

from __future__ import annotations

import contextlib
import importlib.resources
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BUSY_TIMEOUT_MS = 10_000
OPEN_ATTEMPTS = 50  # x OPEN_RETRY_SECONDS: how long a crashed writer's locks may linger
OPEN_RETRY_SECONDS = 0.1
_MIGRATION = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

_log = logging.getLogger(__name__)


class DatabaseVersionError(RuntimeError):
    """The database was written by a newer engine (its schema version is unknown here)."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    script: str


def bundled_migrations() -> list[Migration]:
    """The migration scripts shipped with the engine, oldest first."""
    found = []
    for item in importlib.resources.files("vozata.storage.sqlite.migrations").iterdir():
        match = _MIGRATION.match(item.name)
        if match:
            found.append(Migration(int(match[1]), item.name, item.read_text(encoding="utf-8")))
    return sorted(found, key=lambda migration: migration.version)


def statements(script: str) -> list[str]:
    """Split a script into complete statements (trigger bodies keep their inner `;`)."""
    result: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                result.append(buffer.strip())
            buffer = ""
    if buffer.strip() and not buffer.strip().startswith("--"):
        result.append(buffer.strip())
    return result


def schema_version(db: sqlite3.Connection) -> int:
    return int(db.execute("PRAGMA user_version").fetchone()[0])


def migrate(db: sqlite3.Connection, migrations: list[Migration] | None = None) -> int:
    """Apply the pending migrations, each in its own transaction; returns the final version.

    The version is checked again inside the write transaction, so two processes opening the same
    file never apply a script twice. Raises `DatabaseVersionError` for a newer database.
    """
    migrations = bundled_migrations() if migrations is None else migrations
    latest = max((migration.version for migration in migrations), default=0)
    current = schema_version(db)
    if current > latest:
        raise DatabaseVersionError(f"schema version {current} is newer than {latest}")
    for migration in migrations:
        if migration.version <= current:
            continue
        db.execute("BEGIN IMMEDIATE")
        try:
            if schema_version(db) < migration.version:  # not applied by another process
                for statement in statements(migration.script):
                    db.execute(statement)
                db.execute(f"PRAGMA user_version = {migration.version:d}")
                _log.info("Database migrated to version %d (%s)", migration.version, migration.name)
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")
        current = migration.version
    return schema_version(db)


def _incremental_vacuum(db: sqlite3.Connection) -> None:
    """Switch a file created without `auto_vacuum=INCREMENTAL` (phase 31) to it: one VACUUM."""
    if db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
        return
    _log.info("Converting the database to auto_vacuum=INCREMENTAL (one VACUUM)")
    db.execute("PRAGMA auto_vacuum = INCREMENTAL")
    db.execute("VACUUM")


class Database:
    """`vozata.db`: per-thread connections, serialized writes, migrated on first use.

    Nothing touches the disk until the first `connection()`: the file (and its folder) is
    created and migrated then, so building a repository creates nothing.
    """

    def __init__(self, path: Path, migrations: list[Migration] | None = None) -> None:
        self._path = path
        self._migrations = migrations
        self._migrated = False
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._connections: dict[threading.Thread, sqlite3.Connection] = {}
        self._connections_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def connection(self) -> sqlite3.Connection:
        """This thread's connection (opened on first use, autocommit mode).

        The first one creates and migrates the database; raises `DatabaseVersionError` for a
        database written by a newer engine.
        """
        db: sqlite3.Connection | None = getattr(self._local, "db", None)
        if db is None:
            db = self._open()
        if not self._migrated:
            with self._write_lock:
                if not self._migrated:
                    migrate(db, self._migrations)
                    _incremental_vacuum(db)
                    self._migrated = True
        return db

    def _open(self) -> sqlite3.Connection:
        """A configured connection. Right after a crash Windows can still hold the dead
        process's locks on `-shm` for a moment ("disk I/O error"): retry for a few seconds."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(OPEN_ATTEMPTS):
            try:
                db = self._connect()
                break
            except sqlite3.OperationalError:
                if attempt == OPEN_ATTEMPTS - 1:
                    raise
                _log.warning("Opening %s failed; retrying", self._path)
                time.sleep(OPEN_RETRY_SECONDS)
        self._local.db = db
        with self._connections_lock:
            # Threads come and go (one set per recording): close what finished threads left.
            for thread, old in list(self._connections.items()):
                if not thread.is_alive():
                    old.close()
                    del self._connections[thread]
            self._connections[threading.current_thread()] = db
        return db

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self._path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
            check_same_thread=False,  # only `close()` touches it from another thread
        )
        try:
            db.execute("PRAGMA auto_vacuum = INCREMENTAL")  # takes effect on a new file only
            db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute("PRAGMA foreign_keys = ON")
        except BaseException:
            db.close()
            raise
        return db

    @contextlib.contextmanager
    def write(self, *, durable: bool = False) -> Iterator[sqlite3.Connection]:
        """One write transaction (nested calls join the outer one).

        `durable` commits with `synchronous=FULL` (the per-segment commit of a live transcript).
        """
        with self._write_lock:
            db = self.connection()
            if db.in_transaction:
                yield db
                return
            if durable:
                db.execute("PRAGMA synchronous = FULL")
            try:
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
                db.execute("COMMIT")
            finally:
                if durable:
                    db.execute("PRAGMA synchronous = NORMAL")

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """One consistent snapshot for several queries (joins a transaction already open)."""
        db = self.connection()
        if db.in_transaction:
            yield db
            return
        db.execute("BEGIN")
        try:
            yield db
        finally:
            db.execute("COMMIT")

    def reclaim(self) -> None:
        """Give the pages freed by deleted rows back to the file system (`incremental_vacuum`)."""
        with self._write_lock:
            self.connection().execute("PRAGMA incremental_vacuum").fetchall()

    def close(self) -> None:
        """Close every thread's connection (the next use opens a new one)."""
        with self._connections_lock:
            connections, self._connections = self._connections, {}
        for db in connections.values():
            db.close()
        self._local = threading.local()
