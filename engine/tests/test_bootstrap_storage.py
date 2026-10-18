"""Composition of the storage backends (phase 31): `STORAGE_BACKEND`, the database, recovery."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeLocalizer, FakeSessionObserver
from tests.test_session_recover import SEGMENTS, interrupted_meta
from vozata import bootstrap
from vozata.config import Settings
from vozata.domain import Channel, StorageBackend, StorageInfo
from vozata.labels import SpeakerLabeler
from vozata.storage.audio_cache import WavCache
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.recycle_bin import Send2TrashRecycler
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.search_index import SearchIndex
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.repository import SqliteSessionRepository
from vozata.storage.sqlite.search import SqliteSearch


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def test_every_backend_has_a_repository_audio_store_and_search() -> None:
    assert set(bootstrap.REPOSITORIES) == set(StorageBackend)
    assert set(bootstrap.AUDIO_STORES) == set(StorageBackend)
    assert set(bootstrap.SEARCHES) == set(StorageBackend)


def test_sqlite_is_the_default_backend_with_the_database_in_the_output_dir(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    store = bootstrap.build_store(settings)

    assert isinstance(store, SqliteSessionRepository)
    assert store.database.path == tmp_path / "recordings" / "vozata.db"
    audio = bootstrap.build_audio_store(settings)
    assert isinstance(audio, SqliteAudioStore)  # phase 32
    assert audio._db is store.database
    assert audio.cache.root == tmp_path / "recordings" / "cache"
    assert audio._mixer.channels == 1  # MIX_MODE=mono
    assert isinstance(bootstrap.build_search_index(settings), SqliteSearch)
    assert bootstrap.build_search_index(settings)._db is store.database  # one per file


def test_database_path_moves_the_database(tmp_path: Path) -> None:
    settings = _settings(tmp_path, database_path=tmp_path / "local" / "v.db")

    store = bootstrap.build_store(settings)
    session_id = store.create()

    assert store.database.path == tmp_path / "local" / "v.db"
    assert (tmp_path / "local" / "v.db").is_file()
    assert not (tmp_path / "recordings" / session_id).exists()  # the audio is in the database


def test_the_files_backend_keeps_folders_and_index_db(tmp_path: Path) -> None:
    settings = _settings(tmp_path, storage_backend=StorageBackend.FILES)

    store = bootstrap.build_store(settings)
    assert isinstance(store, FileSessionRepository)
    assert isinstance(store._recycler, Send2TrashRecycler)  # deletes go to the Recycle Bin (36)
    assert isinstance(bootstrap.build_audio_store(settings), FileAudioStore)
    index = bootstrap.build_search_index(settings)
    assert isinstance(index, SearchIndex)
    assert index._path == tmp_path / "recordings" / "index.db"
    assert bootstrap.storage_info(settings) == StorageInfo("files")


def test_storage_info_names_the_database_and_its_onedrive_root(tmp_path: Path) -> None:
    root = tmp_path / "OneDrive"
    local = _settings(tmp_path, onedrive_roots=(root,))
    synced = Settings(output_dir=root / "rec", onedrive_roots=(root,))

    assert bootstrap.storage_info(local) == StorageInfo(
        "sqlite", tmp_path / "recordings" / "vozata.db"
    )
    assert bootstrap.storage_info(synced) == StorageInfo("sqlite", root / "rec" / "vozata.db", root)


def test_the_audio_cache_is_trimmed_at_engine_start(tmp_path: Path) -> None:
    settings = _settings(tmp_path, audio_cache_mb=0)
    stale = tmp_path / "recordings" / "cache" / "20261015_202358" / "mic.wav"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"RIFF")

    bootstrap.clean_audio_cache(settings)

    assert not stale.exists()


def test_cleaning_the_cache_only_logs_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(self: object, keep: object = None) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(WavCache, "clean", fail)

    bootstrap.clean_audio_cache(_settings(tmp_path))
    bootstrap.clean_audio_cache(_settings(tmp_path, storage_backend=StorageBackend.FILES))

    assert "Cleaning the audio cache failed" in caplog.text


def test_opening_a_database_in_onedrive_logs_a_warning_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "OneDrive"
    settings = Settings(output_dir=root / "rec", onedrive_roots=(root,))

    with caplog.at_level(logging.WARNING, logger="vozata.bootstrap"):
        first = bootstrap.open_database(settings)
        second = bootstrap.open_database(settings)

    assert first is second
    [record] = caplog.records
    assert "OneDrive" in record.getMessage() and "DATABASE_PATH" in record.getMessage()


def test_close_databases_forgets_them(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = bootstrap.open_database(settings)

    bootstrap.close_databases()

    assert bootstrap.open_database(settings) is not first


@pytest.mark.parametrize("backend", list(StorageBackend))
def test_a_session_folder_on_the_command_line_opens_the_storage_of_its_parent(
    tmp_path: Path, backend: StorageBackend
) -> None:
    settings = Settings(output_dir=tmp_path / "elsewhere", storage_backend=backend)
    store = bootstrap.build_store(settings, tmp_path / "recordings")
    session_id = store.create()
    store.write_meta(session_id, {"status": "done"})

    folder = bootstrap.open_session_folder(settings, tmp_path / "recordings" / session_id)

    assert folder.session_id == session_id
    assert folder.repository.read_meta(session_id) == {"status": "done"}
    if backend is StorageBackend.SQLITE:
        database = (tmp_path / "recordings" / "vozata.db").resolve()
        assert (folder.minutes_file, folder.diarized_file) == (database, database)
    else:
        assert folder.minutes_file == folder.path / "minutes.md"


def test_sqlite_recovery_pads_the_audio_and_finishes_the_session(tmp_path: Path) -> None:
    """A crash with the SQLite backend: the row says `recording`; the committed chunks are the
    audio (phase 32) and the committed segments the transcript (phase 31)."""
    settings = _settings(tmp_path, generate_minutes=False)
    recovery = bootstrap.build_recovery(settings)
    store = recovery.store
    assert isinstance(store, SqliteSessionRepository)
    assert [type(repair) for repair in recovery._repairs] == [SqliteAudioStore]
    session_id = store.create()
    store.write_meta(session_id, interrupted_meta(session_id, "recording"))
    sink = store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for item in SEGMENTS:
        sink.emit(item)  # no close(): the process died
    audio = recovery._repairs[0]
    for channel, seconds in ((Channel.MIC, 1.0), (Channel.SYSTEM, 0.5)):
        writer = audio.open_writer(session_id, channel)
        writer.write(np.full(round(seconds * settings.sample_rate), 0.1, np.float32), 0.0)
        writer.finalize(0)

    assert recovery.find_interrupted() == [session_id]
    assert recovery.recover(session_id, FakeSessionObserver()) is True

    meta = store.read_meta(session_id)
    assert (meta["status"], meta["duration_seconds"]) == ("done", 1.0)
    assert store.load_transcript(session_id) == SEGMENTS
    assert store.files(session_id) is None
    assert audio.length(session_id, Channel.SYSTEM) == settings.sample_rate  # padded
    assert [hit.session_id for hit in bootstrap.build_search_index(settings).search("hello")] == [
        session_id
    ]
