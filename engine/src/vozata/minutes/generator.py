"""Minutes from a transcript through a `LanguageModel`, map-reducing long meetings."""

from __future__ import annotations

from collections.abc import Sequence

from vozata.domain import ConversationLanguage, TranscriptSegment
from vozata.formatting import render_line
from vozata.labels import SpeakerLabeler
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.ports import LanguageModel, Localizer


class MinutesGenerator:
    """Markdown minutes in the localizer's language.

    A transcript longer than `max_chars` is split at segment boundaries; each part is summarized
    into notes (map) and the notes become the minutes (reduce). `LanguageModelError` propagates.
    """

    def __init__(self, llm: LanguageModel, localizer: Localizer, max_chars: int) -> None:
        self._llm = llm
        self._localizer = localizer
        self._max_chars = max_chars

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
        transcript = "\n".join(lines)
        if len(transcript) <= self._max_chars:
            return self._ask(minutes_prompt(self._localizer, transcript, conversation_language))
        parts = _split(lines, self._max_chars)
        notes = [
            self._ask(map_prompt(self._localizer, part, i, len(parts), conversation_language))
            for i, part in enumerate(parts, start=1)
        ]
        return self._ask(reduce_prompt(self._localizer, notes, conversation_language))

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
