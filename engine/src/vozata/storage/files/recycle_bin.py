"""The Windows Recycle Bin (or the desktop trash elsewhere) through `send2trash` (phase 36)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from send2trash import send2trash


class Send2TrashRecycler:
    """`Recycler`: deleted session folders can still be restored from the Recycle Bin."""

    def __init__(self, send: Callable[[str], None] = send2trash) -> None:
        self._send = send

    def recycle(self, path: Path) -> None:
        """Move `path` to the Recycle Bin; `OSError` when it cannot be moved."""
        self._send(str(path.resolve()))
