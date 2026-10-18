"""`SqliteSessionRepository` (phase 31): the phase 30 contract plus what only the database does."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from tests.storage.repository_contract import RAW, STARTED, RepositoryContract, segment
from vozata.domain import ActionItem, Translation
from vozata.labels import SpeakerLabeler
from vozata.ports import RecoverableStore, SessionNotFoundError, SessionRepository
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "vozata.db")
    yield database
    database.close()


@pytest.fixture
def repo(database: Database, tmp_path: Path) -> SqliteSessionRepository:
    return SqliteSessionRepository(database, tmp_path / "recordings")


class TestSqliteSessionRepository(RepositoryContract):
    @pytest.fixture
    def repository(self, repo: SqliteSessionRepository) -> SessionRepository:
        return repo


def _count(database: Database, table: str) -> int:
    return database.connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _full_session(repo: SqliteSessionRepository) -> str:
    session_id = repo.create(STARTED)
    repo.write_meta(session_id, {"id": session_id, "status": "done"})
    sink = repo.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for raw in RAW:
        sink.emit(raw)
    sink.close()
    repo.write_diarized(session_id, RAW)
    repo.write_edited(session_id, RAW)
    writer = repo.open_translations(session_id)
    writer.append(Translation("mic-000001", "pt", "Olá."))
    writer.close()
    repo.write_speakers(session_id, ["system:1"])
    repo.rename_speakers(session_id, {"system:1": "Ana"})
    repo.write_minutes(session_id, "# Minutes\n")
    repo.write_action_items(session_id, [ActionItem("a1", "Send the report")])
    return session_id


def test_create_makes_no_folder_and_skips_ids_taken_by_folders(
    repo: SqliteSessionRepository, tmp_path: Path
) -> None:
    (tmp_path / "recordings" / "20261015_202358").mkdir(parents=True)  # a file-backend session

    session_id = repo.create(STARTED)

    assert session_id == "20261015_202358_2"
    assert not (tmp_path / "recordings" / session_id).exists()
    assert repo.folder(session_id) is None
    assert repo.files(session_id) is None


def test_create_skips_ids_taken_by_rows_without_a_folder(
    repo: SqliteSessionRepository, database: Database, tmp_path: Path
) -> None:
    repo.write_meta("20261015_202358", {"status": "done"})  # a row, e.g. imported (phase 33)

    session_id = repo.create(STARTED)

    assert session_id == "20261015_202358_2"
    assert not (tmp_path / "recordings" / "20261015_202358").exists()
    assert _count(database, "sessions") == 2


def test_nothing_is_written_to_the_output_folder(
    repo: SqliteSessionRepository, tmp_path: Path
) -> None:
    _full_session(repo)

    assert not (tmp_path / "recordings").exists()


def test_discard_cascades_to_every_table(repo: SqliteSessionRepository, database: Database) -> None:
    session_id = _full_session(repo)
    other = _full_session(repo)
    with database.write() as db:
        db.execute("INSERT INTO audio_chunks VALUES (?, 'mic', 0, 0, 1, x'0000')", (session_id,))

    repo.discard(session_id)

    for table in (
        "segments",
        "translations",
        "speakers",
        "minutes",
        "action_items",
        "audio_chunks",
    ):
        rows = database.connection().execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)
        )
        assert rows.fetchone()[0] == 0, table
    assert _count(database, "segments_fts") == len(RAW)  # only the other session is indexed
    assert repo.list_sessions() == [other]


def test_delete_is_permanent_in_every_table_audio_included(
    repo: SqliteSessionRepository, database: Database
) -> None:
    session_id = _full_session(repo)
    other = _full_session(repo)
    with database.write() as db:
        db.execute("INSERT INTO audio_chunks VALUES (?, 'mic', 0, 0, 1, x'0000')", (session_id,))

    repo.delete(session_id)

    tables = ("segments", "translations", "speakers", "minutes", "action_items", "audio_chunks")
    for table in tables:
        rows = database.connection().execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)
        )
        assert rows.fetchone()[0] == 0, table
    assert _count(database, "sessions") == 1
    assert _count(database, "segments_fts") == len(RAW)  # the search index follows
    assert repo.list_sessions() == [other]


def test_a_session_row_without_metadata_can_be_deleted(repo: SqliteSessionRepository) -> None:
    session_id = repo.create(STARTED)  # a recording that never wrote its metadata

    repo.delete(session_id)

    with pytest.raises(SessionNotFoundError):
        repo.delete(session_id)


def test_metadata_fields_go_to_their_columns_and_the_rest_to_meta_json(
    repo: SqliteSessionRepository, database: Database
) -> None:
    session_id = repo.create(STARTED)
    meta = {
        "schema_version": 1,
        "id": session_id,
        "status": "recording",
        "started_at": "2026-10-15T20:23:58-03:00",
        "ended_at": None,
        "duration_seconds": 12.5,
        "language": "pt",
        "template": "default",
        "title": "Weekly",
        "pauses": [{"start": 1.0, "end": None}],
        "echo_dropped": 3,
    }

    repo.write_meta(session_id, meta)

    row = database.connection().execute(
        "SELECT status, duration_seconds, language, title, meta_json FROM sessions WHERE id = ?",
        (session_id,),
    )
    status, duration, language, title, meta_json = row.fetchone()
    assert (status, duration, language, title) == ("recording", 12.5, "pt", "Weekly")
    rest = json.loads(meta_json)
    assert list(rest) == list(meta)  # every key, in order
    assert rest["pauses"] == meta["pauses"] and rest["status"] is None
    assert repo.read_meta(session_id) == meta
    assert list(repo.read_meta(session_id)) == list(meta)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": 3, "duration_seconds": "12"},  # odd types stay in meta_json, unchanged
        {"duration_seconds": True, "language": {"code": "pt"}},
        {"duration_seconds": 7},
    ],
)
def test_metadata_values_round_trip_with_their_types(
    repo: SqliteSessionRepository, fields: dict
) -> None:
    session_id = repo.create(STARTED)

    repo.write_meta(session_id, fields)

    stored = repo.read_meta(session_id)
    assert stored == fields
    assert [type(value) for value in stored.values()] == [type(v) for v in fields.values()]


def test_a_heartbeat_updates_the_session_row_in_place(
    repo: SqliteSessionRepository, database: Database
) -> None:
    session_id = repo.create(STARTED)
    meta = {"id": session_id, "status": "recording", "duration_seconds": 1.0}
    repo.write_meta(session_id, meta)

    repo.write_meta(session_id, {**meta, "last_heartbeat_at": "2026-10-15T20:24:08-03:00"})

    assert _count(database, "sessions") == 1
    assert repo.read_meta(session_id)["last_heartbeat_at"] == "2026-10-15T20:24:08-03:00"


def test_the_transcript_of_an_unknown_session_is_not_found(repo: SqliteSessionRepository) -> None:
    with pytest.raises(SessionNotFoundError):
        repo.load_transcript_with_source("20991231_000000")


def test_a_segment_is_committed_before_emit_returns(
    repo: SqliteSessionRepository, database: Database
) -> None:
    session_id = repo.create(STARTED)
    sink = repo.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))

    sink.emit(RAW[0])

    other = sqlite3.connect(database.path)  # another connection, as after a crash
    try:
        count = other.execute("SELECT COUNT(*) FROM segments WHERE session_id = ?", (session_id,))
        assert count.fetchone()[0] == 1
    finally:
        other.close()
        sink.close()


def test_minutes_keep_the_session_template_and_when_they_were_written(
    database: Database, tmp_path: Path
) -> None:
    repo_now = SqliteSessionRepository(database, tmp_path / "recordings", lambda: STARTED)
    session_id = repo_now.create(STARTED)
    repo_now.write_meta(session_id, {"status": "done", "template": "one_on_one"})

    repo_now.write_minutes(session_id, "# Minutes\n")

    row = database.connection().execute(
        "SELECT template, generated_at FROM minutes WHERE session_id = ?", (session_id,)
    )
    assert row.fetchone() == ("one_on_one", STARTED.isoformat(timespec="seconds"))


def test_the_live_transcript_needs_no_repair(repo: SqliteSessionRepository) -> None:
    assert not isinstance(repo, RecoverableStore)  # committed segments are complete


def test_sessions_list_newest_first_by_id(repo: SqliteSessionRepository) -> None:
    ids = [repo.create(STARTED + timedelta(seconds=offset)) for offset in (5, 0, 10)]
    for session_id in ids:
        repo.write_meta(session_id, {"status": "done"})

    assert repo.list_sessions() == sorted(ids, reverse=True)


def test_a_duplicate_segment_is_rejected_by_the_key(repo: SqliteSessionRepository) -> None:
    session_id = repo.create(STARTED)

    with pytest.raises(sqlite3.IntegrityError):
        repo.write_diarized(session_id, [segment("mic-1", 0, "a"), segment("mic-1", 1, "b")])

    assert repo.load_transcript_with_source(session_id) == ("raw", [])  # rolled back


def test_the_repository_exposes_its_database(
    repo: SqliteSessionRepository, database: Database
) -> None:
    assert repo.database is database
