"""Read a channel of a live recording across its segment files (phase 61).

The file size is the truth, not the WAV header: a segment still being written (or left by a
crash) has a stale header, but every whole frame after it is a sample that was written. Frames
between segments (a recorder restart) read as silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vozata.domain import Channel
from vozata.recorder.manifest import Manifest, Segment
from vozata.storage.wav_repair import WavRepairError, frames_on_disk, read_layout

_FRAME_BYTES = 2  # mono 16-bit


@dataclass(frozen=True)
class _Span:
    segment: Segment
    path: Path
    frames: int  # readable frames of the file


def segment_frames(path: Path) -> int:
    """Whole frames in a segment file by its size; 0 when it is missing or has no header yet."""
    try:
        with path.open("rb") as file:
            return frames_on_disk(file, read_layout(file, path))
    except (FileNotFoundError, WavRepairError):
        return 0


class SegmentReader:
    """Frames of a recording's channels as one timeline (int16 mono)."""

    def __init__(self, folder: Path, manifest: Manifest) -> None:
        self._folder = folder
        self._manifest = manifest

    def length(self, channel: Channel) -> int:
        """Frames of the channel's timeline, counting what the open segment already holds."""
        return max(
            (span.segment.start_frame + span.frames for span in self._spans(channel)), default=0
        )

    def frames(self, channel: Channel, start: int, count: int) -> np.ndarray:
        """`count` frames from `start` (fewer at the end of the timeline); gaps are silence."""
        end = min(start + count, self.length(channel))
        if end <= start:
            return np.zeros(0, dtype=np.int16)
        out = np.zeros(end - start, dtype=np.int16)
        for span in self._spans(channel):
            first = max(start, span.segment.start_frame)
            last = min(end, span.segment.start_frame + span.frames)
            if last > first:
                out[first - start : last - start] = self._read(
                    span.path, first - span.segment.start_frame, last - first
                )
        return out

    def _spans(self, channel: Channel) -> list[_Span]:
        spans = []
        for segment in self._manifest.segments(channel):
            path = self._folder / segment.file
            on_disk = segment_frames(path)
            frames = min(on_disk, segment.frames) if segment.closed else on_disk
            spans.append(_Span(segment, path, frames))
        return spans

    @staticmethod
    def _read(path: Path, offset: int, count: int) -> np.ndarray:
        with path.open("rb") as file:
            layout = read_layout(file, path)
            file.seek(layout.data_offset + offset * _FRAME_BYTES)
            data = file.read(count * _FRAME_BYTES)
        samples = np.frombuffer(data[: len(data) // _FRAME_BYTES * _FRAME_BYTES], dtype=np.int16)
        if len(samples) < count:  # the file shrank while reading: pad, never fail
            samples = np.concatenate([samples, np.zeros(count - len(samples), dtype=np.int16)])
        return samples
