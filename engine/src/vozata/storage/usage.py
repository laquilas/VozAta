"""Disk usage for Config → Storage (phase 38): the database size (the WAV cache measures and
clears itself, `storage/audio_cache.py`)."""

from __future__ import annotations

from pathlib import Path

_DATABASE_SIDECARS = ("", "-wal", "-shm")  # SQLite keeps recent writes next to the file


def path_size(path: Path) -> int:
    """Bytes of a file, or of every file under a folder; 0 when it does not exist."""
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(_size(item) for item in path.rglob("*") if item.is_file())


def database_size(database: Path) -> int:
    """The database file plus its write-ahead log and shared-memory files."""
    return sum(
        path_size(database.with_name(database.name + suffix)) for suffix in _DATABASE_SIDECARS
    )


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # deleted meanwhile
        return 0
