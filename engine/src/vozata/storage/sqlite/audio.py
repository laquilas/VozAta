"""`SqliteAudioStore`: a session's audio as PCM chunks in `vozata.db` (phase 32).

Implements `SessionAudio` (`AudioStore`, `AudioReader`, `AudioTracks`) and `RecoverableStore`.
Recording goes through `audio_writer.py` (the capture callback never waits on SQLite). The mixed
track is never stored: it is mixed on read with the `MIX_MODE` mixer. Files are built only on
demand, in the `WavCache` (`materialize_wav`, for the diarizer child process).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import weakref
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from vozata.audio.pcm import ChannelTrack, MixedTrack
from vozata.domain import AudioTrack, Channel
from vozata.ports import AudioMixer, AudioTrackWriter, PcmTrack
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio_writer import INSERT_CHUNK, ChunkBatcher, SqliteTrackWriter
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.rows import check_id

CHUNK_SECONDS = 1.0
BACKLOG_SECONDS = 30  # a writer this far behind the capture is logged (audio is still kept)

_log = logging.getLogger(__name__)


class SqliteAudioStore:
    """Mono 16-bit chunks of about `CHUNK_SECONDS` per channel; no chunk is longer."""

    def __init__(
        self,
        database: Database,
        sample_rate: int,
        mixer: AudioMixer,
        cache: WavCache,
        commit_interval: float = 1.0,
    ) -> None:
        self._db = database
        self._rate = sample_rate
        self._mixer = mixer
        self._cache = cache
        self._interval = commit_interval
        self._chunk = max(1, round(CHUNK_SECONDS * sample_rate))
        self._batchers: weakref.WeakValueDictionary[str, ChunkBatcher] = (
            weakref.WeakValueDictionary()
        )
        self._batchers_lock = threading.Lock()

    @property
    def cache(self) -> WavCache:
        return self._cache

    def open_writer(self, session_id: str, channel: Channel) -> AudioTrackWriter:
        """A channel writer; the channels of one session share one commit per second."""
        check_id(session_id)
        with self._batchers_lock:
            batcher = self._batchers.get(session_id)
            if batcher is None:
                batcher = ChunkBatcher(
                    self._db,
                    session_id,
                    self._chunk,
                    self._interval,
                    BACKLOG_SECONDS * self._rate,
                )
                self._batchers[session_id] = batcher
        return SqliteTrackWriter(batcher, channel, self._rate)

    def import_pcm(self, session_id: str, channel: Channel, blocks: Iterable[bytes]) -> int:
        """Replace a channel's audio with `blocks` of mono 16-bit PCM (the folder import of
        phase 33). One transaction, joining the caller's; returns the number of samples."""
        check_id(session_id)
        chunk_bytes = 2 * self._chunk
        with self._db.write() as db:
            db.execute(
                "DELETE FROM audio_chunks WHERE session_id = ? AND channel = ?",
                (session_id, channel.value),
            )
            pending = bytearray()
            seq = start = 0
            for block in blocks:
                pending += block
                rows = []
                while len(pending) >= chunk_bytes:
                    rows.append(
                        (
                            session_id,
                            channel.value,
                            seq,
                            start,
                            self._chunk,
                            bytes(pending[:chunk_bytes]),
                        )
                    )
                    del pending[:chunk_bytes]
                    seq += 1
                    start += self._chunk
                db.executemany(INSERT_CHUNK, rows)
            if len(pending) >= 2:
                frames = len(pending) // 2
                db.execute(
                    INSERT_CHUNK,
                    (session_id, channel.value, seq, start, frames, bytes(pending[: 2 * frames])),
                )
                start += frames
        return start

    def write_mix(self, session_id: str, mixer: AudioMixer) -> None:
        """Nothing to write: the mixed track is computed on read (`track(id, MIXED)`)."""

    def frames(self, session_id: str, channel: Channel, start: int, count: int) -> np.ndarray:
        start = max(start, 0)
        end = start + max(count, 0)
        if end <= start:
            return np.zeros(0, dtype=np.int16)
        rows = (
            self._db.connection()
            .execute(
                "SELECT start_frame, pcm FROM audio_chunks WHERE session_id = ? AND channel = ?"
                " AND start_frame < ? AND start_frame > ? ORDER BY start_frame",
                (session_id, channel.value, end, start - self._chunk),
            )
            .fetchall()
        )
        if not rows:
            return np.zeros(0, dtype=np.int16)
        samples = np.frombuffer(b"".join(row[1] for row in rows), dtype="<i2")
        offset = start - rows[0][0]
        return samples[offset : offset + end - start].astype(np.int16)

    def length(self, session_id: str, channel: Channel) -> int:
        row = (
            self._db.connection()
            .execute(
                "SELECT MAX(start_frame + frames) FROM audio_chunks"
                " WHERE session_id = ? AND channel = ?",
                (session_id, channel.value),
            )
            .fetchone()
        )
        return int(row[0] or 0)

    def sample_rate(self, session_id: str, channel: Channel) -> int:
        return self._rate

    def track(self, session_id: str, track: AudioTrack) -> PcmTrack | None:
        """The track; None when no audio of it was recorded."""
        pcm = self._pcm(session_id, track)
        return pcm if pcm.frames > 0 else None

    def materialize_wav(self, session_id: str, channel: Channel | AudioTrack) -> Path:
        """`cache/<id>/<track>.wav`, built from the chunks (and reused while it matches)."""
        check_id(session_id)
        track = AudioTrack(channel)
        return self._cache.wav(session_id, track.value, self._pcm(session_id, track))

    def repair(self, session_id: str) -> float | None:
        """Pad the shorter channel with silence (phase 17): the committed chunks are the
        recording. Returns its length in seconds."""
        check_id(session_id)
        with self._db.write() as db:
            ends = {channel: self.length(session_id, channel) for channel in Channel}
            total = max(ends.values())
            for channel, end in ends.items():
                self._pad(db, session_id, channel, end, total)
        return round(total / self._rate, 3)

    def delete(self, session_id: str) -> None:
        """Drop a session's audio and cached files, then give the space back to the file
        system in the background (`incremental_vacuum`)."""
        check_id(session_id)
        self._cache.drop(session_id)
        with self._db.write() as db:
            db.execute("DELETE FROM audio_chunks WHERE session_id = ?", (session_id,))
        threading.Thread(target=self._reclaim, name="audio-reclaim", daemon=True).start()

    def _reclaim(self) -> None:
        try:
            self._db.reclaim()
        except Exception:
            _log.exception("Reclaiming the space of deleted audio failed")

    def _pcm(self, session_id: str, track: AudioTrack) -> PcmTrack:
        if track is AudioTrack.MIXED:
            return MixedTrack(self, session_id, self._mixer)
        return ChannelTrack(self, session_id, Channel(track.value))

    def _pad(
        self, db: sqlite3.Connection, session_id: str, channel: Channel, end: int, total: int
    ) -> None:
        row = db.execute(
            "SELECT COALESCE(MAX(seq) + 1, 0) FROM audio_chunks"
            " WHERE session_id = ? AND channel = ?",
            (session_id, channel.value),
        ).fetchone()
        seq = row[0]
        rows = []
        for start in range(end, total, self._chunk):
            frames = min(self._chunk, total - start)
            rows.append((session_id, channel.value, seq, start, frames, bytes(2 * frames)))
            seq += 1
        db.executemany(INSERT_CHUNK, rows)
