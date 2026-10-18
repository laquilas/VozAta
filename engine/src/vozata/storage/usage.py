"""Disk usage for Config → Storage (phase 38): database size and the audio cache folder."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)

AUDIO_CACHE_DIR = "cache"  # `OUTPUT_DIR/cache/`: WAV files materialized for playback (phase 32)
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


def clear_directory(folder: Path) -> int:
    """Delete everything inside `folder` (kept itself); files in use are skipped. Bytes freed."""
    before = path_size(folder)
    if folder.is_dir():
        for item in folder.iterdir():
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                continue
            try:
                item.unlink()
            except OSError as error:
                _log.warning("Could not delete %s from the audio cache: %s", item.name, error)
    return before - path_size(folder)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # deleted meanwhile
        return 0
