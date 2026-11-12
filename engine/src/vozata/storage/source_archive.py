"""The audio sources of recorded meetings, kept after the meeting (phase 66).

A recording that records every device (phase 65) leaves `live/<id>/sources/`: each source's
segment files on the recording's timeline. At ingest they move to `OUTPUT_DIR/sources/<meeting>/`
with `sources.json` (kind, name, selection, segments), so the user can choose other sources for
the minutes after the meeting. They are files, not database rows: a meeting with five devices
would otherwise grow the database by ~0.5 GB an hour. Pruned after `SOURCES_KEEP_DAYS`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from vozata.domain import Channel
from vozata.recorder.manifest import SOURCES_FOLDER, Manifest, Segment
from vozata.recorder.segment_reader import SegmentTimeline

_log = logging.getLogger(__name__)

ARCHIVE_FOLDER = "sources"
INDEX = "sources.json"
_ID_CHARACTERS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


@dataclass(frozen=True)
class ArchivedSource:
    source_id: str
    kind: Channel
    name: str
    selected: bool
    preferred: bool
    frames: int


class SourceArchive:
    def __init__(
        self,
        output_dir: Path,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.root = output_dir / ARCHIVE_FOLDER
        self._now = now

    # -- writing ------------------------------------------------------------------------------

    def keep(self, session_id: str, recording: Path, manifest: Manifest) -> bool:
        """Move the recording's sources here (before `live/<id>` is deleted); False when the
        recording has none. `OSError` when they could not be moved: the caller keeps the folder.
        """
        source_folder = recording / SOURCES_FOLDER
        if not manifest.sources or not source_folder.is_dir():
            return False
        target = self.folder(session_id)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_folder), str(target))
        entries = {
            source_id: {
                "kind": entry.get("kind"),
                "name": entry.get("name"),
                "selected": bool(entry.get("selected")),
                "preferred": bool(entry.get("preferred")),
                "state": entry.get("state"),
                "segments": [_segment_json(s) for s in entry.get("segments") or []],
            }
            for source_id, entry in manifest.sources.items()
        }
        self._write_index(
            session_id,
            {
                "kept_at": self._now().isoformat(timespec="seconds"),
                "sample_rate": manifest.sample_rate,
                "sources": entries,
                "selection_log": manifest.selection_log,
            },
        )
        return True

    def set_selected(self, session_id: str, selected: set[str]) -> None:
        index = self._index(session_id)
        for source_id, entry in index["sources"].items():
            entry["selected"] = source_id in selected
        self._write_index(session_id, index)

    def keep_only_selected(self, session_id: str) -> list[str]:
        """Delete the files of the sources not selected; the ids removed."""
        index = self._index(session_id)
        removed = [i for i, entry in index["sources"].items() if not entry.get("selected")]
        for source_id in removed:
            for segment in index["sources"][source_id].get("segments") or []:
                (self.folder(session_id) / str(segment["file"])).unlink(missing_ok=True)
            del index["sources"][source_id]
        self._write_index(session_id, index)
        return removed

    def remove(self, session_id: str) -> None:
        shutil.rmtree(self.folder(session_id), ignore_errors=True)

    def prune(self, keep_days: int) -> list[str]:
        """Delete the sources kept longer than `keep_days` (0: never); the meetings pruned."""
        if keep_days <= 0 or not self.root.is_dir():
            return []
        limit = self._now() - timedelta(days=keep_days)
        pruned = []
        for folder in sorted(self.root.iterdir()):
            try:
                kept = datetime.fromisoformat(self._index(folder.name)["kept_at"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if kept < limit:
                shutil.rmtree(folder, ignore_errors=True)
                pruned.append(folder.name)
        return pruned

    # -- reading ------------------------------------------------------------------------------

    def has(self, session_id: str) -> bool:
        return (self.folder(session_id) / INDEX).is_file()

    def kept_at(self, session_id: str) -> datetime | None:
        try:
            return datetime.fromisoformat(self._index(session_id)["kept_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self, session_id: str) -> list[ArchivedSource]:
        """The meeting's kept sources; `[]` when it has none."""
        if not self.has(session_id):
            return []
        items = []
        for source_id, entry in self._index(session_id)["sources"].items():
            items.append(
                ArchivedSource(
                    source_id,
                    Channel(str(entry["kind"])),
                    str(entry.get("name") or source_id),
                    bool(entry.get("selected")),
                    bool(entry.get("preferred")),
                    self._timeline(session_id, entry).length(),
                )
            )
        return items

    def frames(self, session_id: str, source_id: str, start: int, count: int) -> np.ndarray:
        """int16 frames of one source; `KeyError` for an unknown source."""
        entry = self._index(session_id)["sources"][source_id]
        return self._timeline(session_id, entry).frames(start, count)

    def folder(self, session_id: str) -> Path:
        if not session_id or not set(session_id.lower()) <= _ID_CHARACTERS | {"_"}:
            raise ValueError(f"Invalid session id {session_id!r}")
        return self.root / session_id

    # -- internals ----------------------------------------------------------------------------

    def _timeline(self, session_id: str, entry: dict[str, Any]) -> SegmentTimeline:
        segments = [Segment(**segment) for segment in entry.get("segments") or []]
        return SegmentTimeline(self.folder(session_id), segments)

    def _index(self, session_id: str) -> dict[str, Any]:
        data = json.loads((self.folder(session_id) / INDEX).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
            raise ValueError(f"{session_id}/{INDEX} is not a source index")
        return data

    def _write_index(self, session_id: str, index: dict[str, Any]) -> None:
        target = self.folder(session_id) / INDEX
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, target)


def _segment_json(segment: Segment) -> dict[str, Any]:
    return {
        "file": segment.file,
        "start_frame": segment.start_frame,
        "frames": segment.frames,
        "closed": True,  # the recording is stopped: every segment is final
        "reason": segment.reason,
    }
