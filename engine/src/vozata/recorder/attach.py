"""What the engine needs to follow a recording of the recorder process (phase 61)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from vozata.domain import Channel
from vozata.recorder.manifest import Manifest


@dataclass(frozen=True)
class RecordingAttach:
    recording_id: str
    folder: Path  # live/<id>/
    started_at: datetime
    device_names: Mapping[Channel, str] = field(default_factory=dict)

    @classmethod
    def of(cls, folder: Path, manifest: Manifest) -> RecordingAttach:
        names = {
            channel: str(manifest.devices.get(channel.value, {}).get("name", channel.value))
            for channel in (Channel.MIC, Channel.SYSTEM)
        }
        return cls(manifest.id, folder, datetime.fromisoformat(manifest.started_at), names)
