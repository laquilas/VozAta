"""Stop step 6 (phase 22): the finished session is added to the search index."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tests.test_session import _Rig, _voice, _words
from vozata.domain import SearchHit, SessionStatus, TranscriptSegment
from vozata.storage.search_index import SearchIndex


class _BrokenIndex:
    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        raise OSError("database is locked")

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        return []


def test_stop_indexes_the_transcript_for_search(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "index.db")
    rig = _Rig(tmp_path, results=[_words("Budget", " approved.")], search_index=index)
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [hit] = index.search("budget")
    assert (hit.session_id, hit.segment_id) == (rig.session.id, "mic-000001")


def test_a_silent_session_is_indexed_as_empty(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "index.db")
    rig = _Rig(tmp_path, search_index=index)
    rig.session.start()

    rig.session.stop()

    assert index.exists()
    assert rig.observer.of("error") == []


def test_an_indexing_failure_is_reported_and_the_session_still_finishes(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hi.")], search_index=_BrokenIndex())
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "index_failed"
    assert "database is locked" in message
    assert rig.session.status is SessionStatus.DONE
    assert rig.store.read_meta(rig.session.id)["status"] == "done"
