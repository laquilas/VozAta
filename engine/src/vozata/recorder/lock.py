"""`live/recorder.lock`: tells the engine and the CLI that a recorder runs, and on which port.

The real single-instance guard is the exclusive port bind; the lock file is only a hint for
readers that do not know the port (it may be stale after a crash: check `/health`).
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

LOCK_FILE = "recorder.lock"


@dataclass(frozen=True)
class RecorderLock:
    pid: int
    port: int
    started_at: str


def write_lock(live: Path, port: int, started_at: str) -> Path:
    live.mkdir(parents=True, exist_ok=True)
    path = live / LOCK_FILE
    path.write_text(
        json.dumps({"pid": os.getpid(), "port": port, "started_at": started_at}), encoding="utf-8"
    )
    return path


def read_lock(live: Path) -> RecorderLock | None:
    """The lock left by the last recorder, or None (missing or unreadable)."""
    try:
        data = json.loads((live / LOCK_FILE).read_text(encoding="utf-8"))
        return RecorderLock(int(data["pid"]), int(data["port"]), str(data["started_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_lock(live: Path) -> None:
    """Remove the lock if it is this process's own."""
    lock = read_lock(live)
    if lock is not None and lock.pid == os.getpid():
        with contextlib.suppress(OSError):
            (live / LOCK_FILE).unlink()
