from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.reindex import run_reindex
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore


class _BrokenIndex(SearchIndex):
    def rebuild(self, store: SessionStore) -> int:
        raise sqlite3.OperationalError("database is locked")


def _run(store: SessionStore, index: SearchIndex) -> tuple[int, str]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    return run_reindex(store, index, console, localizer), out.getvalue()


def test_reindex_indexes_every_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    store.write_meta(paths.id, {"id": paths.id})
    segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Orçamento.", ())
    paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    index = SearchIndex(tmp_path / "index.db")

    code, out = _run(store, index)

    assert code == 0
    assert out == "cli.reindexed(count=1)\n"
    assert [hit.session_id for hit in index.search("orcamento")] == [paths.id]


def test_a_failed_rebuild_exits_1_with_the_reason(tmp_path: Path) -> None:
    code, out = _run(SessionStore(tmp_path), _BrokenIndex(tmp_path / "index.db"))

    assert code == 1
    assert out == "cli.reindex_failed(reason=database is locked)\n"
