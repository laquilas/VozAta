"""Crash safety of the SQLite audio (phase 32): a recording process killed mid-batch.

A child process records two channels through `SqliteAudioStore` (synthetic samples, no audio
hardware) while a thread reports how much audio is committed, and it is hard-killed while it
writes. Every committed sample must be readable and unchanged, and recovery (`repair`) must
give both channels the same length without losing any of it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

import vozata
from tests.storage.repository_contract import STARTED
from vozata.audio.mixer import MonoMixer
from vozata.domain import Channel
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database

RATE = 16000
BLOCK = 1600  # 0.1 s, like a capture callback
STEP = {Channel.MIC: 7, Channel.SYSTEM: 13}  # a different pattern per channel

_WRITER = r"""
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from vozata.audio.mixer import MonoMixer
from vozata.domain import Channel
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

database_path, output, started = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
RATE, BLOCK, STEP = 16000, 1600, {Channel.MIC: 7, Channel.SYSTEM: 13}
database = Database(database_path)
repository = SqliteSessionRepository(database, output)
session_id = repository.create(datetime.fromisoformat(started))
repository.write_meta(session_id, {"id": session_id, "status": "recording"})
store = SqliteAudioStore(
    database, RATE, MonoMixer(), WavCache(output / "cache", 1 << 20), commit_interval=0.05
)
writers = {channel: store.open_writer(session_id, channel) for channel in Channel}


def samples(channel, start, count):
    index = np.arange(start, start + count)
    return (((index * STEP[channel]) % 2000) - 1000).astype(np.float32) / 32767


def report():
    while True:  # what is committed, read through a connection of this thread
        lengths = [store.length(session_id, channel) for channel in Channel]
        print(session_id, *lengths, flush=True)
        time.sleep(0.05)


threading.Thread(target=report, daemon=True).start()
written = 0
while True:  # until killed
    for channel, writer in writers.items():
        writer.write(samples(channel, written, BLOCK), written / RATE)
    written += BLOCK
    time.sleep(0.02)
"""


def _expected(channel: Channel, count: int) -> np.ndarray:
    index = np.arange(count)
    floats = (((index * STEP[channel]) % 2000) - 1000).astype(np.float32) / 32767
    return (np.clip(floats, -1.0, 1.0) * 32767).astype(np.int16)


def test_a_killed_writer_leaves_every_committed_second_and_recovery_evens_the_channels(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "vozata.db"
    src = Path(vozata.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(src)}
    child = subprocess.Popen(
        [sys.executable, "-c", _WRITER, str(database_path), str(tmp_path), STARTED.isoformat()],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        committed = {channel: 0 for channel in Channel}
        session_id = ""
        assert child.stdout is not None
        while min(committed.values()) < 3 * RATE:  # at least three committed seconds
            line = child.stdout.readline()
            assert line, child.stderr.read() if child.stderr else "the writer stopped"
            session_id, mic, system = line.split()
            committed = {Channel.MIC: int(mic), Channel.SYSTEM: int(system)}
    finally:
        child.kill()  # hard kill (TerminateProcess on Windows), most likely mid-batch
        child.wait(10)

    database = Database(database_path)
    try:
        store = SqliteAudioStore(database, RATE, MonoMixer(), WavCache(tmp_path / "cache", 0))
        assert database.connection().execute("PRAGMA integrity_check").fetchone() == ("ok",)
        for channel in Channel:
            length = store.length(session_id, channel)
            assert length >= committed[channel]
            assert length % RATE == 0  # only whole chunks were committed while recording
            frames = store.frames(session_id, channel, 0, length)
            assert frames.tolist() == _expected(channel, length).tolist(), channel

        seconds = store.repair(session_id)

        lengths = {channel: store.length(session_id, channel) for channel in Channel}
        assert lengths[Channel.MIC] == lengths[Channel.SYSTEM]
        assert seconds == lengths[Channel.MIC] / RATE
        assert seconds >= max(committed.values()) / RATE
    finally:
        database.close()
