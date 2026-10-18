from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from vozata.domain import Channel, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionNotFoundError
from vozata.qa.retriever import Retriever, keywords, session_date
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore

FIRST = "20261015_202358"
SECOND = "20261016_090000"


def segment(n: int, text: str, speaker_id: str = "mic") -> TranscriptSegment:
    channel = Channel.MIC if speaker_id == "mic" else Channel.SYSTEM
    return TranscriptSegment(
        f"{channel.value}-{n:06d}", channel, speaker_id, n * 10.0, n * 10.0 + 5, text, ()
    )


def record(
    store: SessionStore, index: SearchIndex, session_id: str, segments: list[TranscriptSegment]
) -> None:
    paths = store.create(datetime.strptime(session_id, "%Y%m%d_%H%M%S"))
    assert paths.id == session_id
    store.write_meta(session_id, {"id": session_id, "status": "done"})
    lines = "".join(json.dumps(s.to_dict()) + "\n" for s in segments)
    paths.transcript_jsonl.write_text(lines, encoding="utf-8")
    index.index_session(session_id, segments)


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "recordings")


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    return SearchIndex(tmp_path / "recordings" / "index.db")


def retriever(store: SessionStore, index: SearchIndex | None, max_chars: int = 12000) -> Retriever:
    localizer = TomlLocalizer("en")
    return Retriever(
        FileSessionRepository(store), index, SpeakerLabeler(localizer), localizer, max_chars
    )


FILLER = [segment(n, f"filler sentence number {n} about nothing in particular") for n in range(20)]


def test_keywords_drop_stopwords_short_words_and_duplicates() -> None:
    assert keywords(
        "What did we decide about the Beta? The beta, x!", {"what", "did", "we", "about", "the"}
    ) == [
        "decide",
        "beta",
    ]


def test_session_date_formats_session_ids() -> None:
    assert session_date(FIRST) == "2026-10-15 20:23"
    assert session_date("whatever") == "whatever"


def test_a_session_that_fits_is_sent_whole(store: SessionStore, index: SearchIndex) -> None:
    segments = [segment(1, "hello"), segment(2, "the beta ships friday", "system")]
    record(store, index, FIRST, segments)

    context = retriever(store, index).retrieve("unrelated question", FIRST)

    assert context.text == (
        "Session 20261015_202358 (2026-10-15 20:23):\n"
        "[00:00:10] Me: hello\n"
        "[00:00:20] Others: the beta ships friday"
    )
    assert context.sessions == {FIRST: tuple(segments)}


def test_a_long_session_keeps_hits_with_two_neighbours_each_side(
    store: SessionStore, index: SearchIndex
) -> None:
    segments = list(FILLER)
    segments[10] = segment(10, "we decided the migration owner is Alice")
    record(store, index, FIRST, segments)

    context = retriever(store, index, max_chars=1000).retrieve("Who owns the migration?", FIRST)

    assert [s.segment_id for s in context.sessions[FIRST]] == [f"mic-{n:06d}" for n in range(8, 13)]
    assert len(context.text) <= 1000
    assert "Alice" in context.text


def test_neighbours_are_dropped_before_the_hit_when_the_budget_is_tight(
    store: SessionStore, index: SearchIndex
) -> None:
    segments = list(FILLER)
    segments[3] = segment(3, "migration plan approved")
    segments[15] = segment(15, "migration is late")
    record(store, index, FIRST, segments)
    header = len("Session 20261015_202358 (2026-10-15 20:23):")
    line = len("[00:00:30] Me: migration plan approved")

    context = retriever(store, index, max_chars=header + 1 + 2 * (line + 1)).retrieve(
        "migration", FIRST
    )

    assert [s.segment_id for s in context.sessions[FIRST]] == ["mic-000003", "mic-000015"]
    assert len(context.text) <= header + 1 + 2 * (line + 1)


def test_a_long_session_without_hits_gives_an_empty_context(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, list(FILLER))

    context = retriever(store, index, max_chars=1000).retrieve("budget", FIRST)

    assert context.empty
    assert context.text == ""


def test_a_long_session_without_an_index_gives_an_empty_context(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, list(FILLER))

    assert retriever(store, None, max_chars=1000).retrieve("filler", FIRST).empty


def test_hits_of_other_sessions_are_ignored_for_one_session(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, list(FILLER))
    record(store, index, SECOND, [segment(1, "budget approved")])

    assert retriever(store, index, max_chars=1000).retrieve("budget", FIRST).empty


def test_an_empty_session_gives_an_empty_context(store: SessionStore, index: SearchIndex) -> None:
    record(store, index, FIRST, [])

    assert retriever(store, index).retrieve("anything", FIRST).empty


def test_an_unknown_session_raises(store: SessionStore, index: SearchIndex) -> None:
    with pytest.raises(SessionNotFoundError):
        retriever(store, index).retrieve("anything", "20990101_000000")


def test_all_sessions_rank_segments_matching_more_terms_first(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, [segment(1, "the beta is late"), segment(2, "nothing here")])
    record(store, index, SECOND, [segment(1, "we decided to delay the beta", "system:1")])

    context = retriever(store, index).retrieve("What did we decide about the beta?")

    assert list(context.sessions) == [SECOND, FIRST]  # SECOND matches two terms
    assert context.sessions[FIRST] == (segment(1, "the beta is late"),)
    assert context.text == (
        "Session 20261016_090000 (2026-10-16 09:00):\n"
        "[00:00:10] User 1: we decided to delay the beta\n\n"
        "Session 20261015_202358 (2026-10-15 20:23):\n"
        "[00:00:10] Me: the beta is late"
    )


def test_all_sessions_are_trimmed_to_the_budget(store: SessionStore, index: SearchIndex) -> None:
    for n, session_id in enumerate(["20261001_100000", "20261002_100000", "20261003_100000"]):
        record(store, index, session_id, [segment(m, f"budget item {n}-{m}") for m in range(5)])

    context = retriever(store, index, max_chars=200).retrieve("budget")

    assert 0 < len(context.text) <= 200
    assert sum(len(segments) for segments in context.sessions.values()) < 15


def test_all_sessions_use_speaker_names(store: SessionStore, index: SearchIndex) -> None:
    record(store, index, FIRST, [segment(1, "budget approved", "system:1")])
    store.paths(FIRST).speakers_json.write_text('{"system:1": {"name": "Alice"}}', encoding="utf-8")

    assert "Alice: budget approved" in retriever(store, index).retrieve("budget").text


def test_all_sessions_skip_deleted_sessions_and_stale_segments(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, [segment(1, "budget approved")])
    index.index_session("20261020_100000", [segment(1, "budget gone")])  # folder never existed
    index.index_session(SECOND, [segment(1, "budget stale")])  # session folder missing too
    index.index_session(FIRST, [segment(1, "budget approved"), segment(9, "budget re-transcribed")])

    context = retriever(store, index).retrieve("budget")

    assert list(context.sessions) == [FIRST]
    assert context.sessions[FIRST] == (segment(1, "budget approved"),)


def test_all_sessions_without_index_or_terms_are_empty(
    store: SessionStore, index: SearchIndex
) -> None:
    record(store, index, FIRST, [segment(1, "the beta")])

    assert retriever(store, None).retrieve("beta").empty
    assert retriever(store, index).retrieve("what is the").empty
