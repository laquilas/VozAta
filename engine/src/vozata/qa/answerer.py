"""Answers about the meetings, streamed from a `LanguageModel` with citations (phase 24)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vozata.domain import Citation
from vozata.formatting import format_timestamp
from vozata.ports import LanguageModel, LanguageModelError, Localizer
from vozata.qa.citations import parse_citations
from vozata.qa.retriever import RetrievedContext

_log = logging.getLogger(__name__)


class ContextRetriever(Protocol):
    def retrieve(self, question: str, session_id: str | None = None) -> RetrievedContext: ...


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]


class MeetingAnswerer:
    """Answers in the localizer's language (`APP_LANGUAGE`), only from the retrieved context.

    Without context the localized "not found" reply is sent and the model is not called. The
    model is released after every answer, as after minutes (VRAM rule); `LanguageModelError`
    propagates.
    """

    def __init__(
        self, llm: LanguageModel, retriever: ContextRetriever, localizer: Localizer
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._t = localizer.t

    def answer(
        self, question: str, session_id: str | None, on_chunk: Callable[[str], None]
    ) -> Answer:
        """Stream the answer through `on_chunk`, in order; raises `SessionNotFoundError`."""
        context = self._retriever.retrieve(question, session_id)
        if context.empty:
            text = self._t("qa.not_found")
            on_chunk(text)
            return Answer(text, ())
        system, user = self.prompt(question, context)
        parts: list[str] = []
        try:
            for chunk in self._llm.stream(system, user):
                parts.append(chunk)
                on_chunk(chunk)
        finally:
            self._release()
        text = "".join(parts)
        return Answer(text, tuple(parse_citations(text, context.sessions)))

    def prompt(self, question: str, context: RetrievedContext) -> tuple[str, str]:
        """(system, user): the rules, the context and the question."""
        session_id, segments = next(iter(context.sessions.items()))
        example = f"{session_id}@{format_timestamp(segments[0].start)}"
        instructions = self._t(
            "qa.instructions",
            output_language=self._t("minutes.output_language"),
            example=example,
            not_found=self._t("qa.not_found"),
        )
        user = "\n\n".join(
            (
                instructions,
                f"{self._t('qa.context_label')}\n{context.text}",
                f"{self._t('qa.question_label')}\n{question.strip()}",
            )
        )
        return self._t("qa.system"), user

    def _release(self) -> None:
        try:
            self._llm.release()
        except LanguageModelError as error:
            _log.warning("Could not release the language model: %s", error)
