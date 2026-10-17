from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.fakes import FakeLanguageModel
from vozata.domain import Channel, Citation, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.ports import LanguageModelError
from vozata.qa.answerer import MeetingAnswerer
from vozata.qa.retriever import RetrievedContext

FIRST = "20261015_202358"
SEGMENT = TranscriptSegment("system-000004", Channel.SYSTEM, "system", 83.4, 88.0, "Alice", ())
CONTEXT = RetrievedContext(
    "Session 20261015_202358 (2026-10-15 20:23):\n[00:01:23] Others: Alice owns the migration",
    {FIRST: (SEGMENT,)},
)


class FixedRetriever:
    def __init__(self, context: RetrievedContext) -> None:
        self.context = context
        self.calls: list[tuple[str, str | None]] = []

    def retrieve(self, question: str, session_id: str | None = None) -> RetrievedContext:
        self.calls.append((question, session_id))
        return self.context


class ChunkedModel(FakeLanguageModel):
    """Streams the given chunks (then raises `error`, if set)."""

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        super().__init__()
        self.chunks = chunks
        self.error = error

    def stream(self, system: str, prompt: str) -> Iterator[str]:
        self.prompts.append((system, prompt, None))
        yield from self.chunks
        if self.error is not None:
            raise self.error


def answerer(llm: FakeLanguageModel, context: RetrievedContext = CONTEXT, language: str = "en"):  # type: ignore[no-untyped-def]
    return MeetingAnswerer(llm, FixedRetriever(context), TomlLocalizer(language))


def test_chunks_are_streamed_in_order_and_citations_parsed() -> None:
    llm = ChunkedModel(["Alice ", "owns it ", f"[{FIRST}@00:01:23]", "."])
    received: list[str] = []

    answer = answerer(llm).answer("Who owns the migration?", FIRST, received.append)

    assert received == ["Alice ", "owns it ", f"[{FIRST}@00:01:23]", "."]
    assert answer.text == f"Alice owns it [{FIRST}@00:01:23]."
    assert answer.citations == (Citation(FIRST, "system-000004", 83.4),)
    assert llm.releases == 1


def test_the_shared_fake_streams_through_the_answerer() -> None:
    received: list[str] = []

    answer = answerer(FakeLanguageModel(["a b"])).answer("q", None, received.append)

    assert received == ["a", "b"]
    assert answer.text == "ab"
    assert answer.citations == ()


def test_the_retriever_gets_the_question_and_scope() -> None:
    retriever = FixedRetriever(CONTEXT)

    MeetingAnswerer(ChunkedModel([]), retriever, TomlLocalizer("en")).answer(
        "q?", FIRST, lambda _: None
    )

    assert retriever.calls == [("q?", FIRST)]


def test_an_empty_context_answers_not_found_without_the_model() -> None:
    llm = ChunkedModel(["never"])
    received: list[str] = []

    answer = answerer(llm, RetrievedContext(), "pt-BR").answer("q", None, received.append)

    assert received == ["Não encontrei isso nas reuniões."]
    assert answer.text == "Não encontrei isso nas reuniões."
    assert answer.citations == ()
    assert llm.prompts == []


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "English"), ("pt-BR", "português do Brasil"), ("es", "español")],
)
def test_the_prompt_is_localized_and_requires_answers_only_from_the_context(
    language: str, expected: str
) -> None:
    llm = ChunkedModel(["ok"])

    answerer(llm, language=language).answer("  Who owns the migration?  ", None, lambda _: None)

    [(system, user, _)] = llm.prompts
    localizer = TomlLocalizer(language)
    assert system == localizer.t("qa.system")
    assert expected in user
    assert f"[{FIRST}@00:01:23]" in user  # a real citation from the context as the example
    assert localizer.t("qa.not_found") in user
    assert CONTEXT.text in user
    assert user.endswith(f"{localizer.t('qa.question_label')}\nWho owns the migration?")


def test_the_english_prompt_says_to_use_only_the_excerpts() -> None:
    llm = ChunkedModel(["ok"])

    answerer(llm).answer("q", None, lambda _: None)

    [(system, user, _)] = llm.prompts
    assert "using only the meeting excerpts" in system
    assert "Never invent" in system
    assert "[session_id@hh:mm:ss]" in user


def test_a_model_failure_propagates_and_still_releases() -> None:
    llm = ChunkedModel(["partial "], LanguageModelError("down"))
    received: list[str] = []

    with pytest.raises(LanguageModelError):
        answerer(llm).answer("q", None, received.append)

    assert received == ["partial "]
    assert llm.releases == 1


def test_a_release_failure_is_only_logged() -> None:
    class FailingRelease(ChunkedModel):
        def release(self) -> None:
            raise LanguageModelError("busy")

    answer = answerer(FailingRelease(["ok"])).answer("q", None, lambda _: None)

    assert answer.text == "ok"
