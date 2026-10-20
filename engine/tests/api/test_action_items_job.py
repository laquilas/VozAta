from __future__ import annotations

import json
import threading
from pathlib import Path

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.api.action_items_job import ActionItemsJob
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.action_items import ActionItemExtractor
from vozata.ports import LanguageModelError
from vozata.processing.gpu_gate import GpuGate, GpuUser
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.processing.queue import ProcessingQueue
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


def _run(tmp_path: Path, build, *, transcript: bool = True, uses_gpu: bool = False, gate=None):  # type: ignore[no-untyped-def]
    store = SessionStore(tmp_path)
    session_id = _session(store, transcript=transcript)
    broadcaster = RecordingBroadcaster()
    queue = ProcessingQueue(gate or GpuGate(), lambda state: None)
    indexed: list[str] = []
    job = ActionItemsJob(
        FileSessionRepository(store),
        build,
        SpeakerLabeler(FakeLocalizer()),
        broadcaster,
        FakeLocalizer(),
        queue=queue,
        uses_gpu=lambda: uses_gpu,
        index=indexed.append,
    )
    queue.start()
    try:
        assert job(session_id)
        assert queue.wait_idle(5)
    finally:
        queue.stop()
    assert indexed == [session_id]
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


class _Blocking(FakeLanguageModel):
    """Blocks in `generate` until `cancel()` (then fails like a closed HTTP request)."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        super().cancel()
        self._cancelled.set()

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.started.set()
        assert self._cancelled.wait(5)
        raise LanguageModelError("request closed")


def test_a_cancelled_extraction_is_redone_with_a_fresh_extractor(tmp_path: Path) -> None:
    gate = GpuGate()
    blocking = _Blocking()
    llms = [blocking, FakeLanguageModel([REPLY])]
    built: list[FakeLanguageModel] = []

    def build() -> ActionItemExtractor:
        built.append(llms.pop(0))
        return _extractor(built[-1])

    def live() -> None:  # a live recording starts while the first attempt runs
        assert blocking.started.wait(5)
        with gate.priority(GpuUser.LIVE):
            pass

    starter = threading.Thread(target=live)
    starter.start()
    session_id, broadcaster = _run(tmp_path, build, uses_gpu=True, gate=gate)
    starter.join(5)

    assert len(built) == 2 and blocking.cancels == 1
    assert broadcaster.of("error") == []
    assert broadcaster.of("action_items_ready") == [
        (session_id, {"session_id": session_id, "count": 2})
    ]


def test_a_meeting_already_in_the_queue_is_refused(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store)
    queue = ProcessingQueue(GpuGate(), lambda state: None)
    job = ActionItemsJob(
        FileSessionRepository(store),
        lambda: _extractor(FakeLanguageModel([REPLY])),
        SpeakerLabeler(FakeLocalizer()),
        RecordingBroadcaster(),
        FakeLocalizer(),
        queue=queue,
    )
    hold = Step(StepKind.INDEX, 1.0, False, lambda token, progress: None)
    assert queue.enqueue(ProcessingJob(session_id, (hold,), on_finished=lambda: None))

    assert job(session_id) is False
