"""Minutes from a transcript through a `LanguageModel`, map-reducing long meetings."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from vozata.domain import ConversationLanguage, TranscriptSegment
from vozata.formatting import render_line, split_lines
from vozata.labels import SpeakerLabeler
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.minutes.template_repository import LocalizedTemplate
from vozata.ports import Cancellable, LanguageModel, LanguageModelError, Localizer

_log = logging.getLogger(__name__)


class MinutesGenerator:
    """Markdown minutes in the localizer's language, with the sections of `template` (phase 20).

    A transcript longer than `max_chars` is split at segment boundaries; each part is summarized
    into notes (map) and the notes become the minutes (reduce). `vocabulary` (phase 19) is given
    to every prompt as a glossary of spellings, and `title` (phase 35) as context.
    `LanguageModelError` propagates.
    The model is released after every job, even a failed one, so it never holds the GPU while
    Whisper loads for the next recording (architecture §6, VRAM rule).
    """

    def __init__(
        self,
        llm: LanguageModel,
        localizer: Localizer,
        max_chars: int,
        template: LocalizedTemplate,
        exclude: Callable[[TranscriptSegment], bool] | None = None,
    ) -> None:
        self._exclude = exclude  # phase 50: voice commands stay out of the prompts
        self._llm = llm
        self._localizer = localizer
        self._max_chars = max_chars
        self._template = template

    @property
    def template_id(self) -> str:
        return self._template.id

    def generate(
        self,
        segments: Sequence[TranscriptSegment],
        labeler: SpeakerLabeler,
        conversation_language: ConversationLanguage,
        vocabulary: Sequence[str] = (),
        title: str | None = None,
        scope: str | None = None,
    ) -> str:
        """`scope` (phase 48) says which part of the meeting the segments are, for minutes of
        part of it."""
        if self._exclude is not None:
            segments = [segment for segment in segments if not self._exclude(segment)]
        if not segments:
            raise ValueError("Cannot write minutes for an empty transcript")
        lines = [
            render_line(segment, labeler.label(segment.speaker_id))
            for segment in sorted(segments, key=lambda segment: segment.start)
        ]
        try:
            return self._summarize(lines, conversation_language, tuple(vocabulary), title, scope)
        finally:
            self._release()

    def _summarize(
        self,
        lines: list[str],
        conversation_language: ConversationLanguage,
        glossary: tuple[str, ...],
        title: str | None,
        scope: str | None,
    ) -> str:
        loc, template, language = self._localizer, self._template, conversation_language
        context = {"glossary": glossary, "title": title, "scope": scope}
        transcript = "\n".join(lines)
        if len(transcript) <= self._max_chars:
            return self._ask(minutes_prompt(loc, template, transcript, language, **context))
        parts = split_lines(lines, self._max_chars)
        notes = [
            self._ask(map_prompt(loc, template, part, i, len(parts), language, **context))
            for i, part in enumerate(parts, start=1)
        ]
        return self._ask(reduce_prompt(loc, template, notes, language, **context))

    def cancel(self) -> None:
        """Stop the model's call in flight (another thread); a no-op when it cannot be cancelled."""
        if isinstance(self._llm, Cancellable):
            self._llm.cancel()

    def close(self) -> None:
        """Close the model's client (its HTTP connections) once this generator is done."""
        self._llm.close()

    def _release(self) -> None:
        try:
            self._llm.release()
        except LanguageModelError as error:
            _log.warning("Could not release the language model: %s", error)

    def _ask(self, prompt: tuple[str, str]) -> str:
        system, user = prompt
        return self._llm.generate(system, user).strip()
