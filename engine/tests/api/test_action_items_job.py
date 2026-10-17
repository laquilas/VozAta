from __future__ import annotations

import json
from pathlib import Path

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.api.action_items_job import ActionItemsJob
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.action_items import ActionItemExtractor
from vozata.ports import LanguageModelError
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

REPLY = json.dumps({"items": [{"description": "Call Bob"}, {"description": "Book room"}]})


def _session(store: SessionStore, *, transcript: bool = True) -> str:
    paths = store.create()
    store.write_meta(paths.id, {"id": paths.id})
    if transcript:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Call Bob.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    return paths.id


def _run(tmp_path: Path, build, *, transcript: bool = True):  # type: ignore[no-untyped-def]
    store = SessionStore(tmp_path)
    session_id = _session(store, transcript=transcript)
    broadcaster = RecordingBroadcaster()
    job = ActionItemsJob(
        FileSessionRepository(store),
        build,
        SpeakerLabeler(FakeLocalizer()),
        broadcaster,
        FakeLocalizer(),
    )
    assert job.wait()  # nothing started yet
    job(session_id)
    assert job.wait(5)
    return session_id, broadcaster


def _extractor(llm: FakeLanguageModel) -> ActionItemExtractor:
    return ActionItemExtractor(llm, FakeLocalizer(), 12000)


def test_success_publishes_the_item_count(tmp_path: Path) -> None:
    session_id, broadcaster = _run(tmp_path, lambda: _extractor(FakeLanguageModel([REPLY])))

    assert broadcaster.of("action_items_ready") == [
        (session_id, {"session_id": session_id, "count": 2})
    ]
    assert broadcaster.of("error") == []


def test_an_empty_transcript_is_reported(tmp_path: Path) -> None:
    session_id, broadcaster = _run(
        tmp_path, lambda: _extractor(FakeLanguageModel()), transcript=False
    )

    [(sid, data)] = broadcaster.of("error")
    assert (sid, data["code"]) == (session_id, "empty_transcript")


def test_a_model_failure_is_reported(tmp_path: Path) -> None:
    _, broadcaster = _run(tmp_path, lambda: _extractor(FakeLanguageModel(["bad", "bad"])))

    [(_, data)] = broadcaster.of("error")
    assert data["code"] == "action_items_failed"
    assert data["message"].startswith("errors.api.action_items_failed(reason=")


def test_an_unexpected_failure_is_reported_as_internal(tmp_path: Path) -> None:
    def broken() -> ActionItemExtractor:
        raise RuntimeError("boom")

    _, broadcaster = _run(tmp_path, broken)

    [(_, data)] = broadcaster.of("error")
    assert data == {"code": "action_items_failed", "message": "errors.api.internal_error"}
    assert issubclass(LanguageModelError, RuntimeError)
