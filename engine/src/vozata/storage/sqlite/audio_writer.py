"""Recording audio into `audio_chunks` (phase 32) without ever making capture wait on SQLite.

`SqliteTrackWriter` (one per channel, an `AudioTrackWriter`) only appends 16-bit PCM to an
in-memory buffer, filling gaps and pauses with silence like `AlignedWavWriter`. `ChunkBatcher`
(one per recording) commits the buffered audio of every channel in one transaction per second
from its own thread, in chunks of `chunk_frames` samples. A channel's last, shorter chunk is
written when its writer is finalized. A failed commit keeps the audio buffered for the next
one; a writer more than `backlog_seconds` behind is logged, and audio is never dropped.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from vozata.audio.wav_writer import to_pcm16
from vozata.domain import Channel
from vozata.storage.sqlite.db import Database

_log = logging.getLogger(__name__)
INSERT_CHUNK = (
    "INSERT INTO audio_chunks (session_id, channel, seq, start_frame, frames, pcm)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)


class ChunkBatcher:
    """The buffered audio of one recording and the thread that commits it."""

    def __init__(
        self,
        database: Database,
        session_id: str,
        chunk_frames: int,
        interval: float = 1.0,
        backlog_frames: int | None = None,
    ) -> None:
        self._db = database
        self._id = session_id
        self._chunk_bytes = 2 * chunk_frames
        self._interval = interval
        self._backlog_bytes = 2 * (
            backlog_frames if backlog_frames is not None else 30 * chunk_frames
        )
        self._lock = threading.Lock()  # the buffers: held only to append or take bytes
        self._commit_lock = threading.Lock()  # one commit at a time
        self._pending: dict[Channel, bytearray] = {}
        self._next: dict[Channel, tuple[int, int]] = {}  # (seq, start_frame) of the next chunk
        self._finished: set[Channel] = set()
        self._behind = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self, channel: Channel) -> None:
        with self._lock:
            self._pending[channel] = bytearray()
            self._next[channel] = (0, 0)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="audio-chunks", daemon=True)
            self._thread.start()

    def append(self, channel: Channel, pcm: bytes) -> None:
        """Buffer `pcm` (called from the capture callback: never touches SQLite)."""
        with self._lock:
            buffer = self._pending[channel]
            buffer += pcm
            behind = len(buffer) > self._backlog_bytes
        if behind and not self._behind:
            _log.warning("Audio of %s is waiting for the database (%s)", self._id, channel.value)
        self._behind = behind

    def finish(self, channel: Channel) -> None:
        """The channel is complete. When every channel is, stop the thread and commit the rest
        (raises when that last commit fails)."""
        with self._lock:
            self._finished.add(channel)
            done = self._finished.issuperset(self._pending)
        if done:
            self._stop.set()
            if self._thread is not None:
                self._thread.join()
            self.commit()

    def commit(self) -> None:
        """Commit every whole chunk buffered (and the rest of finished channels) in one
        transaction; on failure the audio goes back to the buffers and the error is raised."""
        with self._commit_lock:
            taken = self._take()
            if not taken:
                return
            rows, after = self._rows(taken)
            try:
                with self._db.write() as db:
                    db.executemany(INSERT_CHUNK, rows)
            except BaseException:
                with self._lock:
                    for channel, pcm in taken.items():
                        self._pending[channel][:0] = pcm
                raise
            self._next.update(after)

    def _take(self) -> dict[Channel, bytes]:
        taken: dict[Channel, bytes] = {}
        with self._lock:
            for channel, buffer in self._pending.items():
                size = len(buffer)
                if channel not in self._finished:
                    size -= size % self._chunk_bytes
                if size:
                    taken[channel] = bytes(buffer[:size])
                    del buffer[:size]
        return taken

    def _rows(self, taken: dict[Channel, bytes]) -> tuple[list[tuple], dict]:
        rows = []
        after = {}
        for channel, pcm in taken.items():
            seq, frame = self._next[channel]
            for offset in range(0, len(pcm), self._chunk_bytes):
                piece = pcm[offset : offset + self._chunk_bytes]
                rows.append((self._id, channel.value, seq, frame, len(piece) // 2, piece))
                seq += 1
                frame += len(piece) // 2
            after[channel] = (seq, frame)
        return rows, after

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.commit()
            except Exception:
                _log.exception("Saving the audio of %s failed; retrying", self._id)


class SqliteTrackWriter:
    """One channel of a recording (`AudioTrackWriter`): PCM into a `ChunkBatcher`."""

    def __init__(
        self, batcher: ChunkBatcher, channel: Channel, sample_rate: int, tolerance: float = 0.15
    ) -> None:
        self._batcher = batcher
        self._channel = channel
        self._rate = sample_rate
        self._tolerance = round(tolerance * sample_rate)
        self._open = True
        self.samples_written = 0
        self.paused = False
        batcher.open(channel)

    def write(self, samples: np.ndarray, at: float) -> None:
        """Buffer a block whose first sample belongs at session time `at` (see
        `AlignedWavWriter.write`)."""
        expected = round(at * self._rate)
        if expected - self.samples_written > self._tolerance:
            self._append(np.zeros(expected - self.samples_written, dtype=np.float32))
        self._append(np.zeros_like(samples) if self.paused else samples)

    def finalize(self, total_seconds: float) -> None:
        """Pad with silence up to `total_seconds` (never truncate) and complete the channel."""
        if not self._open:
            return
        missing = round(total_seconds * self._rate) - self.samples_written
        if missing > 0:
            self._append(np.zeros(missing, dtype=np.float32))
        self._open = False
        self._batcher.finish(self._channel)

    def _append(self, samples: np.ndarray) -> None:
        if not self._open:
            raise RuntimeError("SqliteTrackWriter is already finalized")
        self._batcher.append(self._channel, to_pcm16(samples).astype("<i2").tobytes())
        self.samples_written += len(samples)
