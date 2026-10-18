"""`SqliteAudioStore` writing (phase 32): chunks, batches, silence, finalize, repair, delete."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tests.storage.audio_contract import RATE, AudioStoreContract
from vozata.audio.mixer import MonoMixer
from vozata.domain import Channel
from vozata.ports import RecoverableStore, SessionAudio
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.audio_writer import ChunkBatcher
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

STARTED = datetime(2026, 10, 15, 20, 23, 58)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "vozata.db")
    yield database
    database.close()


def _store(database: Database, tmp_path: Path, interval: float = 1.0) -> SqliteAudioStore:
    cache = WavCache(tmp_path / "cache", 1 << 30)
    return SqliteAudioStore(database, RATE, MonoMixer(), cache, commit_interval=interval)


def _session(database: Database, tmp_path: Path) -> str:
    return SqliteSessionRepository(database, tmp_path / "recordings").create(STARTED)


def _chunks(database: Database, channel: Channel) -> list[tuple[int, int, int]]:
    rows = database.connection().execute(
        "SELECT seq, start_frame, frames FROM audio_chunks WHERE channel = ? ORDER BY seq",
        (channel.value,),
    )
    return rows.fetchall()


class TestSqliteAudioStore(AudioStoreContract):
    @pytest.fixture
    def audio(self, database: Database, tmp_path: Path) -> SessionAudio:
        return _store(database, tmp_path)

    @pytest.fixture
    def session_id(self, database: Database, tmp_path: Path) -> str:
        return _session(database, tmp_path)


@pytest.fixture
def store(database: Database, tmp_path: Path) -> SqliteAudioStore:
    return _store(database, tmp_path, interval=3600)  # commits only when the test says so


@pytest.fixture
def session_id(database: Database, tmp_path: Path) -> str:
    return _session(database, tmp_path)


def _batcher(store: SqliteAudioStore, session_id: str) -> ChunkBatcher:
    return store._batchers[session_id]


def test_audio_is_stored_in_one_second_chunks_and_the_last_one_is_shorter(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    writer = store.open_writer(session_id, Channel.MIC)
    writer.write(np.full(2 * RATE + 100, 0.5, np.float32), 0.0)

    writer.finalize(0)

    assert _chunks(database, Channel.MIC) == [(0, 0, RATE), (1, RATE, RATE), (2, 2 * RATE, 100)]


def test_only_whole_chunks_are_committed_while_recording(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    mic = store.open_writer(session_id, Channel.MIC)
    system = store.open_writer(session_id, Channel.SYSTEM)
    mic.write(np.zeros(RATE + 10, np.float32), 0.0)
    system.write(np.zeros(RATE // 2, np.float32), 0.0)

    _batcher(store, session_id).commit()

    assert _chunks(database, Channel.MIC) == [(0, 0, RATE)]
    assert _chunks(database, Channel.SYSTEM) == []  # half a second stays in memory
    mic.write(np.zeros(RATE, np.float32), 1.0 + 10 / RATE)
    _batcher(store, session_id).commit()
    assert _chunks(database, Channel.MIC) == [(0, 0, RATE), (1, RATE, RATE)]


def test_the_writer_thread_commits_every_interval(
    database: Database, tmp_path: Path, session_id: str
) -> None:
    store = _store(database, tmp_path, interval=0.01)
    writer = store.open_writer(session_id, Channel.MIC)
    writer.write(np.zeros(RATE, np.float32), 0.0)

    deadline = time.monotonic() + 5
    while not _chunks(database, Channel.MIC) and time.monotonic() < deadline:
        time.sleep(0.01)

    assert _chunks(database, Channel.MIC) == [(0, 0, RATE)]
    writer.finalize(0)


def test_capture_never_waits_for_the_database(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    writer = store.open_writer(session_id, Channel.MIC)
    with database.write():  # the database is busy (held by this thread)
        done = threading.Event()

        def capture() -> None:
            writer.write(np.zeros(5 * RATE, np.float32), 0.0)
            done.set()

        threading.Thread(target=capture).start()
        assert done.wait(2)
    writer.finalize(0)
    assert len(_chunks(database, Channel.MIC)) == 5


def test_a_failed_commit_keeps_the_audio_for_the_next_one(
    store: SqliteAudioStore,
    database: Database,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = store.open_writer(session_id, Channel.MIC)
    writer.write(np.full(RATE, 0.5, np.float32), 0.0)
    batcher = _batcher(store, session_id)
    real = database.write
    monkeypatch.setattr(database, "write", lambda **_: _raise(sqlite3.OperationalError("full")))

    with pytest.raises(sqlite3.OperationalError):
        batcher.commit()

    writer.write(np.full(RATE, 0.25, np.float32), 1.0)
    monkeypatch.setattr(database, "write", real)
    writer.finalize(0)
    assert _chunks(database, Channel.MIC) == [(0, 0, RATE), (1, RATE, RATE)]
    assert store.frames(session_id, Channel.MIC, RATE - 1, 2).tolist() == [16383, 8191]


def test_the_writer_thread_logs_a_failed_commit_and_retries(
    database: Database,
    tmp_path: Path,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(database, tmp_path, interval=0.01)
    writer = store.open_writer(session_id, Channel.MIC)
    real = database.write
    monkeypatch.setattr(database, "write", lambda **_: _raise(sqlite3.OperationalError("locked")))
    writer.write(np.zeros(RATE, np.float32), 0.0)

    deadline = time.monotonic() + 5
    while "retrying" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.01)

    assert "Saving the audio of" in caplog.text
    monkeypatch.setattr(database, "write", real)
    writer.finalize(0)
    assert _chunks(database, Channel.MIC) == [(0, 0, RATE)]


def test_a_writer_far_behind_is_logged_once_and_keeps_every_sample(
    store: SqliteAudioStore,
    database: Database,
    session_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = store.open_writer(session_id, Channel.MIC)
    with caplog.at_level(logging.WARNING):
        for second in range(32):
            writer.write(np.zeros(RATE, np.float32), float(second))

    assert caplog.text.count("waiting for the database") == 1
    writer.finalize(0)
    assert store.length(session_id, Channel.MIC) == 32 * RATE


def test_finalize_pads_both_channels_to_the_same_length(
    store: SqliteAudioStore, session_id: str
) -> None:
    mic = store.open_writer(session_id, Channel.MIC)
    system = store.open_writer(session_id, Channel.SYSTEM)
    mic.write(np.zeros(RATE + 5, np.float32), 0.0)
    system.write(np.zeros(10, np.float32), 0.0)

    for writer in (mic, system):
        writer.finalize((RATE + 5) / RATE)
    mic.finalize(99)  # a second finalize does nothing

    assert store.length(session_id, Channel.MIC) == store.length(session_id, Channel.SYSTEM)
    assert store.length(session_id, Channel.MIC) == RATE + 5


def test_writing_after_finalize_fails(store: SqliteAudioStore, session_id: str) -> None:
    writer = store.open_writer(session_id, Channel.MIC)
    writer.finalize(0)

    with pytest.raises(RuntimeError, match="finalized"):
        writer.write(np.zeros(4, np.float32), 0.0)


def test_repair_pads_the_shorter_channel_with_silence(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    mic = store.open_writer(session_id, Channel.MIC)
    mic.write(np.full(2 * RATE + 3, 0.5, np.float32), 0.0)
    mic.finalize(0)  # a crash: system never got a chunk

    assert isinstance(store, RecoverableStore)
    assert store.repair(session_id) == round((2 * RATE + 3) / RATE, 3)

    assert store.length(session_id, Channel.SYSTEM) == 2 * RATE + 3
    assert [frames for _, _, frames in _chunks(database, Channel.SYSTEM)] == [RATE, RATE, 3]
    assert not store.frames(session_id, Channel.SYSTEM, 0, 3 * RATE).any()
    assert store.repair(session_id) == round((2 * RATE + 3) / RATE, 3)  # nothing more to pad


def test_repair_of_a_session_without_audio_is_zero(
    store: SqliteAudioStore, session_id: str
) -> None:
    assert store.repair(session_id) == 0.0


def test_delete_drops_the_chunks_the_cache_and_reclaims_the_space(
    store: SqliteAudioStore,
    database: Database,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = store.open_writer(session_id, Channel.SYSTEM)
    writer.write(np.zeros(3 * RATE, np.float32), 0.0)
    writer.finalize(0)
    cached = store.materialize_wav(session_id, Channel.SYSTEM)
    reclaimed = threading.Event()
    monkeypatch.setattr(database, "reclaim", reclaimed.set)

    store.delete(session_id)

    assert _chunks(database, Channel.SYSTEM) == []
    assert not cached.exists()
    assert reclaimed.wait(5)


def test_a_failed_reclaim_is_logged(
    store: SqliteAudioStore,
    database: Database,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(database, "reclaim", lambda: _raise(sqlite3.OperationalError("busy")))

    store._reclaim()

    assert "Reclaiming the space" in caplog.text


def test_unknown_ids_are_refused(store: SqliteAudioStore) -> None:
    from vozata.ports import SessionNotFoundError

    with pytest.raises(SessionNotFoundError):
        store.open_writer("../x", Channel.MIC)


def _raise(error: Exception):
    raise error


def test_imported_pcm_is_cut_into_whole_chunks_and_a_shorter_last_one(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    samples = (np.arange(int(2.5 * RATE)) % 1000).astype("<i2")
    blocks = [samples[i : i + 7000].tobytes() for i in range(0, len(samples), 7000)]

    with database.write():  # joins the caller's transaction
        frames = store.import_pcm(session_id, Channel.MIC, blocks)

    assert frames == len(samples)
    assert _chunks(database, Channel.MIC) == [
        (0, 0, RATE),
        (1, RATE, RATE),
        (2, 2 * RATE, RATE // 2),
    ]
    assert np.array_equal(store.frames(session_id, Channel.MIC, 0, len(samples)), samples)


def test_importing_again_replaces_the_channel(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    store.import_pcm(session_id, Channel.SYSTEM, [bytes(4 * RATE)])
    store.import_pcm(session_id, Channel.SYSTEM, [bytes(2 * RATE + 1)])  # an odd byte is dropped

    assert _chunks(database, Channel.SYSTEM) == [(0, 0, RATE)]
    assert store.length(session_id, Channel.SYSTEM) == RATE


def test_an_empty_import_leaves_the_channel_empty(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    assert store.import_pcm(session_id, Channel.MIC, []) == 0
    assert _chunks(database, Channel.MIC) == []


def test_a_failed_import_writes_nothing(
    store: SqliteAudioStore, database: Database, session_id: str
) -> None:
    def blocks():
        yield bytes(4 * RATE)
        raise OSError("unreadable WAV")

    with pytest.raises(OSError):
        store.import_pcm(session_id, Channel.MIC, blocks())

    assert _chunks(database, Channel.MIC) == []
