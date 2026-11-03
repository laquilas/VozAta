"""`live/<id>/engine.json`: the engine session that follows a recording (phase 61).

The engine never writes `recording.json` (the recorder rewrites it from memory), so it keeps its
own link to the recording in this file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LINK_FILE = "engine.json"


def read_link(folder: Path) -> str | None:
    """The engine session that followed this recording, or None."""
    try:
        data = json.loads((folder / LINK_FILE).read_text(encoding="utf-8"))
        return str(data["session_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_link(folder: Path, session_id: str, at: datetime) -> None:
    (folder / LINK_FILE).write_text(
        json.dumps({"session_id": session_id, "attached_at": at.isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
