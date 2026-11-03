"""The no-loss writer of one channel of a live recording (phase 61).

`write(samples, at)` runs on the capture thread: it only aligns the block on the frame timeline
(gaps become silence, paused blocks are written as silence, like `AlignedWavWriter`) and appends
the PCM to an in-memory buffer, which is never dropped. `flush_once()` (the writer thread)
appends the buffer to the open segment file and, every `fsync_seconds`, patches the WAV header,
fsyncs and records the durable frame count in the segment.

Bytes leave the buffer only once they are durable (fsynced). When a write, flush or fsync
fails (a full disk, a OneDrive lock), the segment is closed at its last durable frame and the
bytes after it are written again into a new segment file starting at that frame: nothing is
lost and nothing is counted twice. A new segment is also opened when the file would pass
`max_segment_bytes` (below the WAV 4 GB limit).
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import numpy as np

from vozata.audio.wav_writer import to_pcm16
from vozata.domain import Channel
from vozata.recorder.manifest import (
    REASON_SIZE_LIMIT,
    REASON_START,
    REASON_WRITE_ERROR,
    Segment,
    segment_file,
)
from vozata.storage.wav_repair import WavLayout, write_sizes

_log = logging.getLogger(__name__)

FRAME_BYTES = 2  # mono 16-bit
HEADER_BYTES = 44
_LAYOUT = WavLayout(HEADER_BYTES, FRAME_BYTES)
POLL_SECONDS = 0.1
FIRST_RETRY = 0.5
MAX_RETRY = 5.0
WAV_LIMIT_BYTES = 0xFFFF_FFFF


class TrackWriteError(OSError):
    """The buffered audio could not be made durable before the deadline (it is still kept)."""


def wav_header(sample_rate: int) -> bytes:
    """A mono 16-bit PCM header with zero sizes (patched by `write_sizes`)."""
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        HEADER_BYTES - 8,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * FRAME_BYTES,
        FRAME_BYTES,
        16,
        b"data",
        0,
    )


def _create(path: Path) -> BinaryIO:
    return path.open("x+b")  # never overwrite a file that already holds audio


class DurableTrack:
    def __init__(
        self,
        folder: Path,
        channel: Channel,
        sample_rate: int,
        segments: list[Segment],
        lock: threading.RLock,
        on_durable: Callable[[], None],
        fsync_seconds: float = 2.0,
        max_segment_bytes: int = 2000 * 1024 * 1024,
        start_frame: int = 0,
        first_reason: str = REASON_START,
        tolerance: float = 0.15,
        now: Callable[[], float] = time.monotonic,
        create: Callable[[Path], BinaryIO] = _create,
    ) -> None:
        """`segments` is the channel's list in the manifest; it is changed under `lock`, and
        `on_durable` (which saves the manifest) is called after each change, under `lock` too.
        `start_frame` is where this track's timeline continues (after a recorder restart)."""
        self._folder = folder
        self._channel = channel
        self._rate = sample_rate
        self._segments = segments
        self._lock = lock
        self._on_durable = on_durable
        self._fsync_seconds = fsync_seconds
        self._max_frames = (min(max_segment_bytes, WAV_LIMIT_BYTES) - HEADER_BYTES) // FRAME_BYTES
        self._tolerance = round(tolerance * sample_rate)
        self._now = now
        self._create = create
        self._next_reason = first_reason
        self.paused = False
        self.samples_written = start_frame  # frames accepted on the timeline (with silence)
        self._buffer = bytearray()  # accepted by `write`, not yet taken by the writer
        self._buffer_lock = threading.Lock()
        self._staging = bytearray()  # taken by the writer, not yet in a file (writer only)
        self._unsynced = bytearray()  # in the open file, not yet fsynced
        self._file: BinaryIO | None = None
        self._segment: Segment | None = None
        self._file_frames = 0  # frames in the open file (durable + unsynced)
        self._durable_end = start_frame  # timeline frame after the last durable one
        self._last_sync = now()
        self._retry_at = 0.0
        self._retry = FIRST_RETRY
        self._closing = False
        self._closed = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.write_errors = 0

    @property
    def durable_frames(self) -> int:
        """The timeline frame up to which every sample is on disk."""
        return self._durable_end

    @property
    def pending_seconds(self) -> float:
        """Audio kept in memory, not yet durable."""
        with self._buffer_lock:
            pending = len(self._buffer)
        return (pending + len(self._staging) + len(self._unsynced)) / FRAME_BYTES / self._rate

    def write(self, samples: np.ndarray, at: float) -> None:
        """Accept a block whose first sample belongs at recording time `at` (never blocks)."""
        expected = round(at * self._rate)
        silence = expected - self.samples_written
        with self._buffer_lock:
            if silence > self._tolerance:
                self._buffer += bytes(silence * FRAME_BYTES)
                self.samples_written += silence
            block = np.zeros(len(samples), dtype=np.int16) if self.paused else to_pcm16(samples)
            self._buffer += block.tobytes()
            self.samples_written += len(samples)

    def pad_to(self, frames: int) -> None:
        """Accept silence until the timeline holds `frames` frames (never shortens it)."""
        with self._buffer_lock:
            missing = frames - self.samples_written
            if missing > 0:
                self._buffer += bytes(missing * FRAME_BYTES)
                self.samples_written += missing

    def start(self) -> None:
        """Run `flush_once` on a writer thread until `close`."""
        self._thread = threading.Thread(
            target=self._run, name=f"track-{self._channel.value}", daemon=True
        )
        self._thread.start()

    def close(self, timeout: float = 30.0) -> None:
        """Write everything, fsync, close the segment; `TrackWriteError` if not durable in time.

        On a timeout the writer thread keeps trying: the audio stays in memory.
        """
        self._closing = True
        self._wake.set()
        if self._thread is None:
            deadline = self._now() + timeout
            while not self._closed.is_set():
                self.flush_once()
                if not self._closed.is_set() and self._now() >= deadline:
                    break
                if not self._closed.is_set():
                    time.sleep(min(POLL_SECONDS, max(0.0, self._retry_at - self._now())))
        else:
            self._thread.join(timeout)
        if not self._closed.is_set():
            raise TrackWriteError(
                f"{self._channel.value}: {self.pending_seconds:.1f} s of audio not yet on disk"
            )

    def flush_once(self) -> None:
        """One writer step: append the buffer, fsync when due (or when closing)."""
        if self._closed.is_set() or self._now() < self._retry_at:
            return
        with self._buffer_lock:
            self._staging += self._buffer
            self._buffer = bytearray()
        closing = self._closing
        try:
            self._append()
            if self._file is not None and (
                closing or self._now() - self._last_sync >= self._fsync_seconds
            ):
                self._sync()
            if closing and not self._buffer:
                self._finish()
            self._retry = FIRST_RETRY
        except OSError as error:
            self._failed(error)

    def _append(self) -> None:
        """Move the staged bytes into segment files; a byte leaves `_staging` once written."""
        while self._staging:
            if self._file is None:
                self._open()
            room = (self._max_frames - self._file_frames) * FRAME_BYTES
            if room <= 0:
                self._sync()
                self._close_segment(REASON_SIZE_LIMIT)
                continue
            part = bytes(self._staging[:room])
            self._file.write(part)  # type: ignore[union-attr]
            del self._staging[: len(part)]
            self._unsynced += part
            self._file_frames += len(part) // FRAME_BYTES

    def _open(self) -> None:
        index = len(self._segments) + 1
        while True:
            path = self._folder / segment_file(self._channel, index)
            try:
                file = self._create(path)
                break
            except FileExistsError:
                index += 1
        try:
            file.write(wav_header(self._rate))
        except OSError:
            file.close()
            raise
        self._file = file
        self._file_frames = 0
        self._segment = Segment(path.name, self._durable_end, 0, reason=self._next_reason)
        with self._lock:
            self._segments.append(self._segment)
            self._on_durable()

    def _sync(self) -> None:
        file, segment = self._file, self._segment
        if file is None or segment is None:
            return
        file.flush()
        write_sizes(file, _LAYOUT, self._file_frames)  # flushes and fsyncs
        file.seek(0, 2)
        self._unsynced = bytearray()
        self._durable_end = segment.start_frame + self._file_frames
        self._last_sync = self._now()
        with self._lock:
            segment.frames = self._file_frames
            self._on_durable()

    def _close_segment(self, next_reason: str) -> None:
        file, segment = self._file, self._segment
        self._file = None
        self._segment = None
        self._next_reason = next_reason
        if file is not None:
            try:
                file.close()
            except OSError:
                _log.warning("Closing %s failed", segment.file if segment else "?", exc_info=True)
        if segment is not None:
            with self._lock:
                segment.frames = self._durable_end - segment.start_frame
                segment.closed = True
                self._on_durable()

    def _finish(self) -> None:
        self._close_segment(REASON_START)
        self._closed.set()

    def _failed(self, error: OSError) -> None:
        """Close the segment at its last durable frame; what came after is written again."""
        self.write_errors += 1
        _log.warning(
            "Writing %s failed (%s); the audio is kept and goes to a new file",
            self._channel.value,
            error,
        )
        self._staging[:0] = self._unsynced
        self._unsynced = bytearray()
        try:
            self._close_segment(REASON_WRITE_ERROR)
        except OSError:
            _log.warning("Saving the manifest failed", exc_info=True)
        self._next_reason = REASON_WRITE_ERROR
        self._retry_at = self._now() + self._retry
        self._retry = min(self._retry * 2, MAX_RETRY)

    def _run(self) -> None:
        while not self._closed.is_set():
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()
            try:
                self.flush_once()
            except Exception:  # never let the writer thread die: the audio is in memory
                _log.exception("Track writer step failed")
                time.sleep(POLL_SECONDS)
