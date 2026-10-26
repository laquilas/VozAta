"""Phase 59: the jobs finish the meeting's requests they were started for."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.api.ask_job import AskJob
from vozata.api.minutes_job import MinutesJob
from vozata.api.partial_minutes_job import PartialMinutesJob, PartialRequest
from vozata.api.request_log import RequestLog, record, refused
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError
from vozata.processing.gpu_gate import GpuGate
from vozata.processing.queue import ProcessingQueue
from vozata.qa.answerer import Answer
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


class _Failing(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise LanguageModelError("connection refused")


class _Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.sessions = SessionStore(tmp_path)
        self.paths = self.sessions.create()
        self.sessions.write_meta(self.paths.id, {"language": "en"})
        self.store = FileSessionRepository(self.sessions)
        self.session_id = self.paths.id
        self.broadcaster = RecordingBroadcaster()
        self.log = RequestLog(self.store, self.broadcaster)
        self.queue = ProcessingQueue(GpuGate(), lambda state: None)

    def transcript(self) -> None:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hi.", ())
        self.paths.transcript_jsonl.write_text(
            json.dumps(segment.to_dict()) + "\n", encoding="utf-8"
        )

    def entries(self) -> list[tuple[str, str, str | None, str | None]]:
        return [
            (entry.kind, entry.status, entry.result_id, entry.message)
            for entry in self.store.read_requests(self.session_id)
        ]

    def generator(self, llm: FakeLanguageModel) -> MinutesGenerator:
        return MinutesGenerator(llm, FakeLocalizer(), 12000, minutes_template())


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    made = _Rig(tmp_path)
    yield made
    made.queue.stop()


def _minutes_job(rig: _Rig, llm: FakeLanguageModel) -> MinutesJob:
    rig.queue.start()
    return MinutesJob(
        rig.store,
        lambda template: rig.generator(llm),
        SpeakerLabeler(FakeLocalizer()),
        rig.broadcaster,
        FakeLocalizer(),
        queue=rig.queue,
        requests=rig.log,
    )


def test_minutes_again_finish_their_request(rig: _Rig) -> None:
    rig.transcript()
    job = _minutes_job(rig, FakeLanguageModel(["# Minutes"]))
    record(rig.log, rig.session_id, "minutes", "app")

    assert job(rig.session_id)
    assert rig.queue.wait_idle(5)

    assert rig.entries() == [("minutes", "done", None, None)]


def test_failed_minutes_again_carry_the_error_code(rig: _Rig) -> None:
    rig.transcript()
    job = _minutes_job(rig, _Failing())
    record(rig.log, rig.session_id, "minutes", "app")

    assert job(rig.session_id)
    assert rig.queue.wait_idle(5)

    assert rig.entries() == [("minutes", "failed", None, "minutes_failed")]


def test_minutes_again_without_a_transcript_fail_as_empty(rig: _Rig) -> None:
    job = _minutes_job(rig, FakeLanguageModel(["# Minutes"]))
    record(rig.log, rig.session_id, "minutes", "app")

    assert job(rig.session_id)
    assert rig.queue.wait_idle(5)

    assert rig.entries() == [("minutes", "failed", None, "empty_transcript")]


def _partial_job(rig: _Rig, llm: FakeLanguageModel) -> PartialMinutesJob:
    return PartialMinutesJob(
        lambda template: rig.generator(llm),
        rig.store,
        SpeakerLabeler(FakeLocalizer()),
        rig.broadcaster,
        FakeLocalizer(),
        new_id=lambda: "p1",
        requests=rig.log,
    )


def test_partial_minutes_finish_their_request_with_the_result(rig: _Rig) -> None:
    rig.transcript()
    job = _partial_job(rig, FakeLanguageModel(["# So far"]))
    request_id = record(rig.log, rig.session_id, "minutes_so_far", "button")

    job.start(PartialRequest(rig.session_id, 0.0, None, "button", True, None, request_id))
    assert job.wait(5)

    assert rig.entries() == [("minutes_so_far", "done", "p1", None)]


def test_failed_partial_minutes_fail_their_request(rig: _Rig) -> None:
    job = _partial_job(rig, FakeLanguageModel(["# So far"]))  # no transcript: empty range
    request_id = record(rig.log, rig.session_id, "range_minutes", "range")

    job.start(PartialRequest(rig.session_id, 0.0, 10.0, "range", False, None, request_id))
    assert job.wait(5)

    assert rig.entries() == [("range_minutes", "failed", None, "empty_range")]


def test_partial_minutes_without_a_request_record_nothing(rig: _Rig) -> None:
    rig.transcript()
    job = _partial_job(rig, FakeLanguageModel(["# So far"]))

    job.start(PartialRequest(rig.session_id, 0.0, None, "button", True))
    assert job.wait(5)

    assert rig.entries() == []


class _Answerer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def answer(self, question: str, session_id: str | None, on_chunk: object) -> Answer:
        if self.error is not None:
            raise self.error
        return Answer("Yes.", ())


@pytest.mark.parametrize(
    ("error", "expected"),
    [(None, ("done", None)), (LanguageModelError("down"), ("failed", "answer_failed"))],
)
def test_an_answer_finishes_its_question(
    rig: _Rig, error: Exception | None, expected: tuple[str, str | None]
) -> None:
    job = AskJob(lambda: _Answerer(error), rig.broadcaster, FakeLocalizer(), requests=rig.log)
    record(rig.log, rig.session_id, "ask", "app", text="Who?", result_id="a1")

    assert job.start("a1", "Who?", rig.session_id)
    assert job.wait(5)

    [entry] = rig.store.read_requests(rig.session_id)
    assert (entry.status, entry.message) == expected


def test_a_question_about_every_meeting_records_nothing(rig: _Rig) -> None:
    job = AskJob(lambda: _Answerer(), rig.broadcaster, FakeLocalizer(), requests=rig.log)

    assert job.start("a1", "Who?", None)
    assert job.wait(5)

    assert rig.broadcaster.of("request_updated") == []


def test_a_refused_request_is_ignored_with_its_code(rig: _Rig) -> None:
    request_id = record(rig.log, rig.session_id, "minutes", "app")

    refused(rig.log, rig.session_id, request_id, "session_still_active")

    assert rig.entries() == [("minutes", "ignored", None, "session_still_active")]


def test_without_a_log_nothing_is_recorded(rig: _Rig) -> None:
    assert record(None, rig.session_id, "minutes", "app") is None
    refused(None, rig.session_id, "r1", "busy")  # no error
    refused(rig.log, rig.session_id, None, "busy")

    assert rig.entries() == []
