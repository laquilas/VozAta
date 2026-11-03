"""`recording.json`: what the recorder knows about a recording (phase 61).

Written by the recorder, read by the engine and the UI. Each channel's audio is a list of
segment files on one frame timeline (`start_frame` = the frame of the segment's first sample).
Normally a channel has one segment, `mic.wav` / `system.wav`, for the whole meeting; a new
segment is opened only when writing fails, the size guard is reached or the recorder restarts.
The frames between two segments (a recorder restart) are silence and are listed in `gaps`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vozata.domain import Channel

SCHEMA_VERSION = 1
MANIFEST = "recording.json"
LIVE_FOLDER = "live"

RECORDING = "recording"
PAUSED = "paused"
STOPPED = "stopped"
ACTIVE = (RECORDING, PAUSED)

REASON_START = "start"
REASON_WRITE_ERROR = "write_error"
REASON_SIZE_LIMIT = "size_limit"
REASON_RESTART = "recorder_restart"

_REPLACE_ATTEMPTS = 20
_REPLACE_WAIT = 0.05  # OneDrive briefly locks files it syncs


def live_dir(output_dir: Path) -> Path:
    """Where the recorder keeps its recordings until the engine has stored them."""
    return output_dir / LIVE_FOLDER


def segment_file(channel: Channel, index: int) -> str:
    """`mic.wav` for the first segment of a channel, then `mic-0002.wav`, `mic-0003.wav`..."""
    return f"{channel.value}.wav" if index == 1 else f"{channel.value}-{index:04d}.wav"


@dataclass
class Segment:
    file: str
    start_frame: int
    frames: int = 0  # durable frames (fsynced); the file may already hold more
    closed: bool = False
    reason: str = REASON_START

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


@dataclass
class Gap:
    start_frame: int
    end_frame: int
    reason: str = REASON_RESTART


@dataclass
class Manifest:
    id: str
    started_at: str  # ISO 8601 with the local offset
    sample_rate: int
    status: str = RECORDING
    incarnation: int = 1
    recorder_pid: int | None = None
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    channels: dict[str, list[Segment]] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    pauses: list[dict[str, float | None]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    last_heartbeat_at: str | None = None
    duration_seconds: float = 0.0
    stopped_at: str | None = None
    stop_reason: str | None = None
    engine: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    def segments(self, channel: Channel) -> list[Segment]:
        return self.channels.setdefault(channel.value, [])

    def open_segment(self, channel: Channel) -> Segment | None:
        segments = self.segments(channel)
        return segments[-1] if segments and not segments[-1].closed else None

    def frames_total(self, channel: Channel) -> int:
        """The channel's timeline length by the durable frames of its segments."""
        return max((segment.end_frame for segment in self.segments(channel)), default=0)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Manifest:
        values = dict(data)
        values["channels"] = {
            name: [Segment(**segment) for segment in segments]
            for name, segments in (data.get("channels") or {}).items()
        }
        values["gaps"] = [Gap(**gap) for gap in data.get("gaps") or []]
        known = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in values.items() if key in known})


def read_manifest(folder: Path) -> Manifest:
    """The manifest of the recording in `folder`; `OSError` / `ValueError` when unreadable."""
    data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{folder / MANIFEST} is not an object")
    return Manifest.from_json(data)


def write_manifest(folder: Path, manifest: Manifest) -> None:
    """Replace `recording.json` atomically (a reader never sees half a file); retries a lock."""
    target = folder / MANIFEST
    temporary = folder / f"{MANIFEST}.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(manifest.to_json(), file, ensure_ascii=False, indent=1)
        file.flush()
        os.fsync(file.fileno())
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_WAIT)


def list_recordings(output_dir: Path) -> list[str]:
    """Ids of the folders under `live/` that hold a manifest, oldest first."""
    folder = live_dir(output_dir)
    if not folder.is_dir():
        return []
    return sorted(entry.name for entry in folder.iterdir() if (entry / MANIFEST).is_file())
