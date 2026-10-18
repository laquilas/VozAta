"""Where `vozata.db` lives: a database in a OneDrive-synced folder is at risk (phase 31).

OneDrive locks a file while it uploads it and syncs the database without its `-wal` file, which
can corrupt a database in use; the engine warns at start and in `GET /health`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path


def _normalized(path: Path) -> Path:
    return Path(os.path.normcase(os.path.abspath(path)))


def onedrive_root(path: Path, roots: Sequence[Path]) -> Path | None:
    """The OneDrive root that contains `path` (case-insensitive on Windows), else None."""
    target = _normalized(path)
    for root in roots:
        if target.is_relative_to(_normalized(root)):
            return root
    return None
