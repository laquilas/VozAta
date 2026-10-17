"""Minutes from a transcript through a `LanguageModel`, map-reducing long meetings."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from vozata.domain import ConversationLanguage, TranscriptSegment
from vozata.formatting import render_line
from vozata.labels import SpeakerLabeler
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.minutes.template_repository import LocalizedTemplate
from vozata.ports import LanguageModel, LanguageModelError, Localizer

_log = logging.getLogger(__name__)


class MinutesGenerator:
    """Markdown minutes in the localizer's language, with the sections of `template` (phase 20).

    A transcript longer than `max_chars` is split at segment boundaries; each part is summarized
    into notes (map) and the notes become the minutes (reduce). `LanguageModelError` propagates.
    The model is released after every job, even a failed one, so it never holds the GPU while
    Whisper loads for the next recording (architecture §6, VRAM rule).
    """

    def __init__(
        self,
        llm: LanguageModel,
        localizer: Localizer,
        max_chars: int,
        template: LocalizedTemplate,
    ) -> None:
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
    ) -> str:
        if not segments:
            raise ValueError("Cannot write minutes for an empty transcript")
        lines = [
            render_line(segment, labeler.label(segment.speaker_id))
            for segment in sorted(segments, key=lambda segment: segment.start)
        ]
        try:
            return self._summarize(lines, conversation_language)
        finally:
            self._release()

    def _summarize(self, lines: list[str], conversation_language: ConversationLanguage) -> str:
        loc, template, language = self._localizer, self._template, conversation_language
        transcript = "\n".join(lines)
        if len(transcript) <= self._max_chars:
            return self._ask(minutes_prompt(loc, template, transcript, language))
        parts = _split(lines, self._max_chars)
        notes = [
            self._ask(map_prompt(loc, template, part, i, len(parts), language))
            for i, part in enumerate(parts, start=1)
        ]
        return self._ask(reduce_prompt(loc, template, notes, language))

    def _release(self) -> None:
        try:
            self._llm.release()
        except LanguageModelError as error:
            _log.warning("Could not release the language model: %s", error)

    def _ask(self, prompt: tuple[str, str]) -> str:
        system, user = prompt
        return self._llm.generate(system, user).strip()


def _split(lines: Sequence[str], max_chars: int) -> list[str]:
    """Group whole lines into parts of at most `max_chars` (a longer line stands alone)."""
    parts: list[list[str]] = []
    size = 0
    for line in lines:
        if parts and size + 1 + len(line) <= max_chars:
            parts[-1].append(line)
            size += 1 + len(line)
        else:
            parts.append([line])
            size = len(line)
    return ["\n".join(part) for part in parts]
