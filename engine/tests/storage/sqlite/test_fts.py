"""`segments_fts` (phase 31): the triggers keep the index on each session's best transcript."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from tests.storage.repository_contract import STARTED, segment
from vozata.domain import SNIPPET_END, SNIPPET_START, SearchHit
from vozata.labels import SpeakerLabeler
from vozata.ports import TranscriptSearch
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository
from vozata.storage.sqlite.search import SqliteSearch

RAW = [segment("mic-000001", 1.0, "the budget is approved"), segment("mic-000002", 4.0, "next")]


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "vozata.db")
    yield database
    database.close()


@pytest.fixture
def repo(database: Database, tmp_path: Path) -> SqliteSessionRepository:
    return SqliteSessionRepository(database, tmp_path / "recordings")


@pytest.fixture
def search(database: Database) -> SqliteSearch:
    return SqliteSearch(database)


def _recorded(repo: SqliteSessionRepository, segments=RAW, offset: int = 0) -> str:
    from datetime import timedelta

    session_id = repo.create(STARTED + timedelta(minutes=offset))
    repo.write_meta(session_id, {"status": "done"})
    sink = repo.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for item in segments:
        sink.emit(item)
    sink.close()
    return session_id


def _ids(search: SqliteSearch, query: str) -> list[str]:
    return [hit.segment_id for hit in search.search(query)]


def _indexed(database: Database) -> int:
    return database.connection().execute("SELECT COUNT(*) FROM segments_fts").fetchone()[0]


def test_satisfies_the_port(search: SqliteSearch) -> None:
    assert isinstance(search, TranscriptSearch)


def test_live_segments_are_searchable_as_they_are_committed(
    repo: SqliteSessionRepository, search: SqliteSearch
) -> None:
    session_id = _recorded(repo)

    assert search.search("budget") == [
        SearchHit(
            session_id,
            "mic-000001",
            1.0,
            "mic",
            f"the {SNIPPET_START}budget{SNIPPET_END} is approved",
        )
    ]


def test_search_is_accent_insensitive_and_the_last_term_a_prefix(
    repo: SqliteSessionRepository, search: SqliteSearch
) -> None:
    _recorded(repo, [segment("mic-000001", 0.0, "a decisão foi tomada")])

    assert _ids(search, "DECISAO") == ["mic-000001"]
    assert _ids(search, "decisao tom") == ["mic-000001"]
    assert search.search("  ?! ") == []
    assert search.search('budget" OR "x') == []  # FTS syntax is plain text


def test_diarizing_replaces_the_raw_segments_in_the_index(
    repo: SqliteSessionRepository, search: SqliteSearch, database: Database
) -> None:
    session_id = _recorded(repo)

    repo.write_diarized(session_id, [segment("mic-000001", 1.0, "the budget is approved", "x")])

    assert [hit.speaker_id for hit in search.search("budget")] == ["x"]
    assert _ids(search, "next") == []
    assert _indexed(database) == 1


def test_an_edit_is_indexed_and_reverting_it_brings_back_the_diarized_text(
    repo: SqliteSessionRepository, search: SqliteSearch, database: Database
) -> None:
    session_id = _recorded(repo)
    repo.write_diarized(session_id, RAW)

    repo.write_edited(session_id, [segment("mic-000001", 1.0, "the forecast is approved")])
    assert _ids(search, "forecast") == ["mic-000001"]
    assert _ids(search, "budget") == []

    repo.write_edited(session_id, [segment("mic-000001", 1.0, "the plan is approved")])
    assert _ids(search, "forecast") == [] and _ids(search, "plan") == ["mic-000001"]

    assert repo.delete_edited(session_id)
    assert _ids(search, "plan") == []
    assert sorted(_ids(search, "budget") + _ids(search, "next")) == ["mic-000001", "mic-000002"]
    assert _indexed(database) == len(RAW)


def test_reverting_an_edit_without_diarization_brings_back_the_raw_text(
    repo: SqliteSessionRepository, search: SqliteSearch
) -> None:
    session_id = _recorded(repo)
    repo.write_edited(session_id, [segment("mic-000001", 1.0, "edited words")])

    repo.delete_edited(session_id)

    assert _ids(search, "edited") == []
    assert _ids(search, "budget") == ["mic-000001"]


def test_one_session_does_not_change_the_index_of_another(
    repo: SqliteSessionRepository, search: SqliteSearch
) -> None:
    first = _recorded(repo)
    second = _recorded(repo, offset=1)

    repo.write_edited(second, [segment("mic-000001", 1.0, "other words")])

    assert [hit.session_id for hit in search.search("budget")] == [first]


def test_a_changed_row_is_indexed_with_its_new_text(
    repo: SqliteSessionRepository, search: SqliteSearch, database: Database
) -> None:
    _recorded(repo)

    with database.write() as db:
        db.execute("UPDATE segments SET text = 'renamed topic' WHERE segment_id = 'mic-000001'")

    assert _ids(search, "renamed") == ["mic-000001"]
    assert _ids(search, "budget") == []


def test_rebuild_indexes_the_best_source_of_every_session_again(
    repo: SqliteSessionRepository, search: SqliteSearch, database: Database
) -> None:
    first = _recorded(repo)
    _recorded(repo, offset=1)
    repo.write_edited(first, [segment("mic-000001", 1.0, "edited budget")])
    with database.write() as db:
        db.execute("DELETE FROM segments_fts")

    assert search.rebuild(repo) == 2

    assert sorted(hit.session_id for hit in search.search("budget")) == sorted(
        [first, repo.list_sessions()[0]]
    )
    assert _indexed(database) == 1 + len(RAW)


def test_index_session_and_ensure_change_nothing(
    repo: SqliteSessionRepository, search: SqliteSearch, database: Database
) -> None:
    session_id = _recorded(repo)

    search.index_session(session_id, [])
    search.ensure(repo)

    assert _ids(search, "budget") == ["mic-000001"]
    assert not (database.path.parent / "index.db").exists()
