from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest

from tests.api.conftest import Api, RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.api.ask_job import AskJob
from vozata.domain import Channel, Citation, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.ports import LanguageModelError
from vozata.qa.answerer import Answer, MeetingAnswerer
from vozata.qa.retriever import Retriever
from vozata.storage.search_index import SearchIndex

SESSION = "20261015_202358"


class StreamingModel(FakeLanguageModel):
    def __init__(self, chunks: list[str]) -> None:
        super().__init__()
        self.chunks = chunks

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        self.prompts.append((system, prompt, None))
        yield from self.chunks


class StubAnswerer:
    def __init__(
        self,
        chunks: list[str] = (),  # type: ignore[assignment]
        citations: tuple[Citation, ...] = (),
        error: Exception | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.citations = citations
        self.error = error
        self.gate = gate
        self.calls: list[tuple[str, str | None]] = []

    def answer(
        self, question: str, session_id: str | None, on_chunk: Callable[[str], None]
    ) -> Answer:
        self.calls.append((question, session_id))
        if self.gate is not None:
            assert self.gate.wait(5)
        for chunk in self.chunks:
            on_chunk(chunk)
        if self.error is not None:
            raise self.error
        return Answer("".join(self.chunks), self.citations)


def job(answerer: StubAnswerer, broadcaster: RecordingBroadcaster) -> AskJob:
    return AskJob(lambda: answerer, broadcaster, FakeLocalizer())


def test_the_job_streams_chunks_then_done_with_citations() -> None:
    broadcaster = RecordingBroadcaster()
    citation = Citation(SESSION, "mic-000001", 12.5)
    ask = job(StubAnswerer(["Alice ", "owns it"], (citation,)), broadcaster)

    assert ask.start("a1", "Who?", SESSION)
    assert ask.wait(5)

    assert broadcaster.published == [
        ("answer_chunk", SESSION, {"answer_id": "a1", "text": "Alice "}),
        ("answer_chunk", SESSION, {"answer_id": "a1", "text": "owns it"}),
        (
            "answer_done",
            SESSION,
            {
                "answer_id": "a1",
                "citations": [{"session_id": SESSION, "segment_id": "mic-000001", "start": 12.5}],
                "error": None,
            },
        ),
    ]


def test_a_model_failure_ends_the_answer_with_a_localized_error() -> None:
    broadcaster = RecordingBroadcaster()
    ask = job(StubAnswerer(["par"], error=LanguageModelError("down")), broadcaster)

    ask.start("a1", "Who?", None)
    assert ask.wait(5)

    assert broadcaster.of("answer_done") == [
        (
            None,
            {
                "answer_id": "a1",
                "citations": [],
                "error": "errors.api.answer_failed(reason=down)",
            },
        )
    ]


def test_an_unexpected_failure_ends_the_answer_with_the_internal_error() -> None:
    broadcaster = RecordingBroadcaster()
    ask = job(StubAnswerer(error=RuntimeError("bug")), broadcaster)

    ask.start("a1", "Who?", None)
    assert ask.wait(5)

    [(_, data)] = broadcaster.of("answer_done")
    assert data["error"] == "errors.api.internal_error"


def test_one_question_at_a_time() -> None:
    broadcaster = RecordingBroadcaster()
    gate = threading.Event()
    ask = job(StubAnswerer(["x"], gate=gate), broadcaster)

    assert ask.start("a1", "first", None)
    assert not ask.start("a2", "second", None)
    gate.set()
    assert ask.wait(5)
    assert ask.start("a3", "third", None)
    assert ask.wait(5)


def test_wait_without_a_job_returns_at_once() -> None:
    assert job(StubAnswerer(), RecordingBroadcaster()).wait(0)


@pytest.fixture
def asking(tmp_path: Path) -> Iterator[tuple[Api, StubAnswerer, AskJob]]:
    api = Api(tmp_path)
    answerer = StubAnswerer(["ok"])
    ask = job(answerer, api.broadcaster)
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, ask=ask)
    with api.client:
        yield api, answerer, ask


def test_post_ask_accepts_and_streams_the_answer(asking: tuple[Api, StubAnswerer, AskJob]) -> None:
    api, answerer, ask = asking

    response = api.client.post("/ask", json={"question": "  Who owns it?  "})

    assert response.status_code == 202
    answer_id = response.json()["answer_id"]
    assert len(answer_id) == 32
    assert ask.wait(5)
    assert answerer.calls == [("Who owns it?", None)]
    assert [kind for kind, _, _ in api.broadcaster.published] == ["answer_chunk", "answer_done"]
    assert api.broadcaster.of("answer_done")[0][1]["answer_id"] == answer_id


def test_post_ask_scoped_to_a_session(asking: tuple[Api, StubAnswerer, AskJob]) -> None:
    api, answerer, ask = asking
    api.store.create(datetime(2026, 10, 15, 20, 23, 58))
    api.store.write_meta(SESSION, {"id": SESSION, "status": "done"})

    response = api.client.post("/ask", json={"question": "q", "session_id": SESSION})

    assert response.status_code == 202
    assert ask.wait(5)
    assert answerer.calls == [("q", SESSION)]
    assert {session_id for _, session_id, _ in api.broadcaster.published} == {SESSION}


def test_post_ask_for_an_unknown_session_is_404(asking: tuple[Api, StubAnswerer, AskJob]) -> None:
    api, answerer, _ = asking

    response = api.client.post("/ask", json={"question": "q", "session_id": "20990101_000000"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    assert answerer.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "q", "x": 1},
    ],
)
def test_post_ask_rejects_invalid_questions(
    asking: tuple[Api, StubAnswerer, AskJob], body: dict[str, object]
) -> None:
    api, _, _ = asking

    response = api.client.post("/ask", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_post_ask_while_answering_is_409(tmp_path: Path) -> None:
    api = Api(tmp_path)
    gate = threading.Event()
    ask = job(StubAnswerer(["x"], gate=gate), api.broadcaster)
    api.app.state.container = dataclasses.replace(api.app.state.container, ask=ask)
    with api.client:
        assert api.client.post("/ask", json={"question": "one"}).status_code == 202
        response = api.client.post("/ask", json={"question": "two"})
        gate.set()
        assert ask.wait(5)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "answer_in_progress"
    assert "Another question" in response.json()["error"]["message"]


def test_post_ask_without_an_answerer_is_503(api: Api) -> None:
    response = api.client.post("/ask", json={"question": "q"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ask_unavailable"


def test_end_to_end_with_the_real_answerer_and_index(tmp_path: Path) -> None:
    api = Api(tmp_path)
    index = SearchIndex(tmp_path / "recordings" / "index.db")
    paths = api.store.paths(api.store.create(datetime(2026, 10, 15, 20, 23, 58)))
    api.store.write_meta(SESSION, {"id": SESSION, "status": "done"})
    segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 83.4, 88.0, "Alice owns it", ())
    paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    index.index_session(SESSION, [segment])
    llm = StreamingModel(["Alice ", f"[{SESSION}@00:01:23]"])
    localizer = TomlLocalizer("en")
    retriever = Retriever(api.store, index, SpeakerLabeler(localizer), localizer, 12000)
    ask = AskJob(lambda: MeetingAnswerer(llm, retriever, localizer), api.broadcaster, localizer)
    api.app.state.container = dataclasses.replace(api.app.state.container, ask=ask)
    with api.client:
        response = api.client.post("/ask", json={"question": "Who owns the migration?"})
        assert ask.wait(5)

    answer_id = response.json()["answer_id"]
    assert api.broadcaster.published == [
        ("answer_chunk", None, {"answer_id": answer_id, "text": "Alice "}),
        ("answer_chunk", None, {"answer_id": answer_id, "text": f"[{SESSION}@00:01:23]"}),
        (
            "answer_done",
            None,
            {
                "answer_id": answer_id,
                "citations": [{"session_id": SESSION, "segment_id": "mic-000001", "start": 83.4}],
                "error": None,
            },
        ),
    ]
    assert llm.releases == 1
