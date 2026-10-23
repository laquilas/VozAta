"""A question about the whole meeting so far, asked by voice while recording (phase 50).

Unlike Ask (phase 24), which keeps the lines matching the question's keywords when a meeting is
long, "what was decided?" needs everything: a long transcript is first read part by part into
notes for the question (map), then the answer is written from the notes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from vozata.domain import TranscriptSegment
from vozata.formatting import render_line, split_lines
from vozata.labels import SpeakerLabeler
from vozata.ports import LanguageModel, LanguageModelError, Localizer, SessionRepository
from vozata.qa.answerer import Answer

_log = logging.getLogger(__name__)
_NOTES_SEPARATOR = "\n\n---\n\n"


class MeetingSoFarAnswerer:
    """The `Answerer` of voice questions: streams the answer through `on_chunk`, no citations.
    `exclude` leaves the voice commands themselves out. The model is released after every answer
    (VRAM rule); `LanguageModelError` propagates."""

    def __init__(
        self,
        llm: LanguageModel,
        store: SessionRepository,
        labeler: SpeakerLabeler,
        localizer: Localizer,
        max_chars: int,
        exclude: Callable[[TranscriptSegment], bool] | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._labeler = labeler
        self._t = localizer.t
        self._max_chars = max_chars
        self._exclude = exclude

    def answer(
        self, question: str, session_id: str | None, on_chunk: Callable[[str], None]
    ) -> Answer:
        if session_id is None:
            raise ValueError("A question about the meeting so far needs its session")
        segments = [
            segment
            for segment in self._store.load_transcript(session_id)
            if self._exclude is None or not self._exclude(segment)
        ]
        if not segments:
            text = self._t("qa.not_found")
            on_chunk(text)
            return Answer(text, ())
        named = self._labeler.with_names(self._store.speaker_names(session_id))
        lines = [
            render_line(segment, named.label(segment.speaker_id))
            for segment in sorted(segments, key=lambda segment: segment.start)
        ]
        try:
            label, context = self._context(question, lines)
            parts: list[str] = []
            for chunk in self._llm.stream(
                self._t("qa.system"), self._user(question, label, context)
            ):
                parts.append(chunk)
                on_chunk(chunk)
        finally:
            self._release()
        return Answer("".join(parts), ())

    def _context(self, question: str, lines: list[str]) -> tuple[str, str]:
        transcript = "\n".join(lines)
        if len(transcript) <= self._max_chars:
            return self._t("qa.context_label"), transcript
        parts = split_lines(lines, self._max_chars)
        notes = [
            self._llm.generate(
                self._t("qa.system"),
                "\n\n".join(
                    (
                        self._t("qa.map_instructions", part=index, total=len(parts)),
                        f"{self._t('qa.question_label')}\n{question.strip()}",
                        f"{self._t('qa.context_label')}\n{part}",
                    )
                ),
            ).strip()
            for index, part in enumerate(parts, start=1)
        ]
        return self._t("qa.notes_label"), _NOTES_SEPARATOR.join(notes)

    def _user(self, question: str, label: str, context: str) -> str:
        instructions = self._t(
            "qa.so_far_instructions",
            output_language=self._t("minutes.output_language"),
            not_found=self._t("qa.not_found"),
        )
        return "\n\n".join(
            (
                instructions,
                f"{label}\n{context}",
                f"{self._t('qa.question_label')}\n{question.strip()}",
            )
        )

    def _release(self) -> None:
        try:
            self._llm.release()
        except LanguageModelError as error:
            _log.warning("Could not release the language model: %s", error)
