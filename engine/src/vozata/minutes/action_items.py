"""Action items (description, owner, due date) from a transcript as structured data (phase 23)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from vozata.domain import ActionItem, ConversationLanguage, TranscriptSegment, optional_text
from vozata.formatting import format_timestamp
from vozata.labels import SpeakerLabeler
from vozata.ports import LanguageModel, LanguageModelError, Localizer

_log = logging.getLogger(__name__)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "owner": {"type": ["string", "null"]},
                    "due": {"type": ["string", "null"]},
                    "source_segment_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["description", "owner", "due", "source_segment_ids"],
            },
        }
    },
    "required": ["items"],
}


class ActionItemsError(LanguageModelError):
    """The model's reply was not valid action-item JSON, even after one retry."""


class InvalidReplyError(ValueError):
    """One reply that does not match `SCHEMA`."""


class ActionItemExtractor:
    """Asks the model for the meeting's action items with a JSON schema (`format` in Ollama).

    Lines are given with their segment ids so items link back to `source_segment_ids` (unknown
    ids are dropped). A transcript longer than `max_chars` is split at segment boundaries and the
    items of every part are concatenated. An invalid reply is retried once, then
    `ActionItemsError` is raised; `LanguageModelError` propagates. The model is released after
    every job (VRAM rule).
    """

    def __init__(self, llm: LanguageModel, localizer: Localizer, max_chars: int) -> None:
        self._llm = llm
        self._t = localizer.t
        self._max_chars = max_chars

    def extract(
        self,
        segments: Sequence[TranscriptSegment],
        labeler: SpeakerLabeler,
        conversation_language: ConversationLanguage,
        vocabulary: Sequence[str] = (),
        meeting_date: str | None = None,
    ) -> list[ActionItem]:
        ordered = sorted(segments, key=lambda segment: segment.start)
        known = {segment.segment_id for segment in ordered}
        lines = [_line(segment, labeler.label(segment.speaker_id)) for segment in ordered]
        parts = _split(lines, self._max_chars)
        try:
            raw = [
                item
                for index, part in enumerate(parts, start=1)
                for item in self._ask(
                    self.prompt(
                        part, index, len(parts), conversation_language, vocabulary, meeting_date
                    )
                )
            ]
        finally:
            self._release()
        return [
            ActionItem(
                id=f"a{number}",
                description=description,
                owner=owner,
                due=due,
                source_segment_ids=tuple(i for i in ids if i in known),
            )
            for number, (description, owner, due, ids) in enumerate(raw, start=1)
        ]

    def prompt(
        self,
        transcript: str,
        part: int,
        total: int,
        conversation_language: ConversationLanguage,
        vocabulary: Sequence[str] = (),
        meeting_date: str | None = None,
    ) -> tuple[str, str]:
        """(system, user) for one part of the transcript."""
        blocks = [
            self._t(
                "action_items.instructions",
                conversation_language=self._t(f"languages.{conversation_language.value}"),
                output_language=self._t("minutes.output_language"),
            )
        ]
        if meeting_date:
            blocks.append(self._t("action_items.meeting_date", date=meeting_date))
        if total > 1:
            blocks.append(self._t("action_items.part", part=part, total=total))
        if vocabulary:
            blocks.append(self._t("minutes.glossary", terms=", ".join(vocabulary)))
        blocks.append(f"{self._t('action_items.transcript_label')}\n{transcript}")
        return self._t("action_items.system"), "\n\n".join(blocks)

    def _ask(self, prompt: tuple[str, str]) -> list[tuple[str, str | None, str | None, list[str]]]:
        system, user = prompt
        for attempt in (1, 2):
            reply = self._llm.generate(system, user, SCHEMA)
            try:
                return parse_reply(reply)
            except InvalidReplyError as error:
                _log.warning("Invalid action-item reply (attempt %d): %s", attempt, error)
                last = error
        raise ActionItemsError(f"The model did not return valid action items: {last}")

    def _release(self) -> None:
        try:
            self._llm.release()
        except LanguageModelError as error:
            _log.warning("Could not release the language model: %s", error)


def parse_reply(reply: str) -> list[tuple[str, str | None, str | None, list[str]]]:
    """(description, owner, due, source ids) per item; raises `InvalidReplyError`."""
    try:
        data = json.loads(reply)
    except ValueError as error:
        raise InvalidReplyError(f"not JSON ({error})") from None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise InvalidReplyError('no "items" list')
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            raise InvalidReplyError("an item is not an object")
        description = optional_text(item.get("description"))
        if description is None:
            raise InvalidReplyError("an item has no description")
        ids = item.get("source_segment_ids") or []
        if not isinstance(ids, list):
            raise InvalidReplyError("source_segment_ids is not a list")
        parsed.append(
            (
                description,
                optional_text(item.get("owner")),
                optional_text(item.get("due")),
                [str(i) for i in ids],
            )
        )
    return parsed


def _line(segment: TranscriptSegment, label: str) -> str:
    """`[segment_id] [hh:mm:ss] Label: text`: the id lets the model cite its sources."""
    timestamp = format_timestamp(segment.start)
    return f"[{segment.segment_id}] [{timestamp}] {label}: {segment.text.strip()}"


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
