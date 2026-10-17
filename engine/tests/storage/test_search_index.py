from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from vozata.domain import SNIPPET_END, SNIPPET_START, Channel, SearchHit, TranscriptSegment
from vozata.ports import TranscriptSearch
from vozata.storage.search_index import SearchIndex, fts_query
from vozata.storage.session_store import SessionStore


def _segment(segment_id: str, text: str, start: float = 1.0) -> TranscriptSegment:
    return TranscriptSegment(segment_id, Channel.MIC, "mic", start, start + 2, text, ())


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    return SearchIndex(tmp_path / "index.db")


def _mark(word: str) -> str:
    return f"{SNIPPET_START}{word}{SNIPPET_END}"


def test_search_index_satisfies_the_port(index: SearchIndex) -> None:
    assert isinstance(index, TranscriptSearch)


def test_search_finds_an_indexed_segment(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "the budget is approved", 83.5)])

    hits = index.search("budget")

    assert hits == [
        SearchHit(
            "20261015_202358", "mic-000001", 83.5, "mic", f"the {_mark('budget')} is approved"
        )
    ]


def test_search_is_accent_insensitive(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "a decisão foi tomada")])

    assert [hit.segment_id for hit in index.search("decisao")] == ["mic-000001"]
    assert [hit.segment_id for hit in index.search("DECISÃO")] == ["mic-000001"]


def test_last_term_matches_as_a_prefix(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "we discussed the roadmap")])

    assert len(index.search("disc")) == 1
    assert index.search("cussed") == []


def test_every_term_must_match(index: SearchIndex) -> None:
    index.index_session(
        "20261015_202358",
        [_segment("mic-000001", "budget for marketing"), _segment("mic-000002", "budget only")],
    )

    assert [hit.segment_id for hit in index.search("budget marketing")] == ["mic-000001"]


def test_reindexing_a_session_replaces_its_segments(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "old words")])
    index.index_session("20261015_202358", [_segment("mic-000001", "new words")])

    assert index.search("old") == []
    assert len(index.search("new")) == 1


def test_reindexing_one_session_keeps_the_others(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "shared topic")])
    index.index_session("20261016_090000", [_segment("mic-000001", "shared topic")])
    index.index_session("20261016_090000", [])

    assert [hit.session_id for hit in index.search("topic")] == ["20261015_202358"]


def test_hits_are_ranked_and_limited(index: SearchIndex) -> None:
    index.index_session(
        "20261015_202358",
        [
            _segment("mic-000001", "a long sentence that mentions launch once among many words"),
            _segment("mic-000002", "launch launch launch"),
            _segment("mic-000003", "launch plan"),
        ],
    )

    hits = index.search("launch", limit=2)

    assert len(hits) == 2
    assert hits[0].segment_id == "mic-000002"


def test_snippet_marks_every_match(index: SearchIndex) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "Decisão: a decisão final")])

    [hit] = index.search("decisao")

    assert hit.snippet == f"{_mark('Decisão')}: a {_mark('decisão')} final"


@pytest.mark.parametrize(
    "query",
    ['"', '""', "*", "OR", "AND", "NOT", "NEAR(", "budget OR", '"budget', "text:budget", "(", "^"],
)
def test_fts_syntax_in_the_query_is_handled_safely(index: SearchIndex, query: str) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "budget OR text")])

    index.search(query)  # never raises sqlite3.OperationalError


def test_operators_are_searched_as_plain_words(index: SearchIndex) -> None:
    index.index_session(
        "20261015_202358",
        [_segment("mic-000001", "cats or dogs"), _segment("mic-000002", "cats and birds")],
    )

    assert [hit.segment_id for hit in index.search("cats OR")] == ["mic-000001"]
    assert len(index.search("cats birds")) == 1


@pytest.mark.parametrize("query", ["", "   ", "*", '"', "?!"])
def test_a_query_without_words_finds_nothing(index: SearchIndex, query: str) -> None:
    index.index_session("20261015_202358", [_segment("mic-000001", "anything")])

    assert index.search(query) == []


def test_search_on_a_new_index_finds_nothing(index: SearchIndex) -> None:
    assert index.search("anything") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("budget", '"budget"*'),
        ("Budget  plan", '"Budget" "plan"*'),
        ('say "hi" OR *', '"say" "hi" "OR"*'),
        ("decisão", '"decisão"*'),
        ("", None),
        ("*?", None),
    ],
)
def test_fts_query_quotes_terms_and_prefixes_the_last(text: str, expected: str | None) -> None:
    assert fts_query(text) == expected


def test_exists_reports_whether_the_database_file_exists(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "sub" / "index.db")
    assert not index.exists()

    index.index_session("20261015_202358", [])

    assert index.exists()


def test_rebuild_indexes_every_session_from_its_best_transcript(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, now=lambda: datetime(2026, 10, 15, 20, 23, 58))
    first = store.create()
    store.write_meta(first.id, {"id": first.id})
    _write(first.transcript_jsonl, _segment("mic-000001", "raw words"))
    _write(first.edited_jsonl, _segment("mic-000001", "edited words"))
    second = store.create(datetime(2026, 10, 16, 9, 0, 0))
    store.write_meta(second.id, {"id": second.id})
    _write(second.transcript_jsonl, _segment("mic-000001", "second meeting"))
    index = SearchIndex(tmp_path / "index.db")
    index.index_session("20200101_000000", [_segment("mic-000001", "stale meeting")])

    count = index.rebuild(store)

    assert count == 2
    assert index.search("raw") == []
    assert [hit.session_id for hit in index.search("edited")] == [first.id]
    assert [hit.session_id for hit in index.search("meeting")] == [second.id]


def _store_with_one_session(tmp_path: Path) -> SessionStore:
    store = SessionStore(tmp_path / "recordings")
    paths = store.create(datetime(2026, 10, 15, 20, 23, 58))
    store.write_meta(paths.id, {"id": paths.id})
    _write(paths.transcript_jsonl, _segment("mic-000001", "first words"))
    return store


def test_ensure_builds_a_missing_index_from_existing_sessions(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "recordings" / "index.db")

    index.ensure(_store_with_one_session(tmp_path))

    assert len(index.search("first")) == 1


def test_ensure_keeps_an_existing_index(tmp_path: Path) -> None:
    store = _store_with_one_session(tmp_path)
    index = SearchIndex(tmp_path / "recordings" / "index.db")
    index.index_session("20200101_000000", [_segment("mic-000001", "kept words")])

    index.ensure(store)

    assert index.search("first") == []
    assert len(index.search("kept")) == 1


def test_ensure_creates_nothing_without_sessions(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "recordings" / "index.db")

    index.ensure(SessionStore(tmp_path / "recordings"))

    assert not (tmp_path / "recordings").exists()


def test_ensure_logs_a_failure_instead_of_raising(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken(SearchIndex):
        def rebuild(self, store: SessionStore) -> int:
            raise OSError("disk full")

    Broken(tmp_path / "recordings" / "index.db").ensure(_store_with_one_session(tmp_path))

    assert "Building the search index failed" in caplog.text


def _write(path: Path, *segments: TranscriptSegment) -> None:
    lines = [json.dumps(segment.to_dict()) for segment in segments]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
