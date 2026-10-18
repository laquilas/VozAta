"""(Re)extract and store a session's action items (stop step, API job)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from vozata.domain import ActionItem, ConversationLanguage, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_minutes import EmptyTranscriptError, stored_vocabulary
from vozata.ports import SessionRepository


class Extractor(Protocol):
    """What this module needs from `ActionItemExtractor`."""

    def extract(
        self,
        segments: Sequence[TranscriptSegment],
        labeler: SpeakerLabeler,
        conversation_language: ConversationLanguage,
        vocabulary: Sequence[str] = (),
        meeting_date: str | None = None,
    ) -> list[ActionItem]: ...


def write_session_action_items(
    store: SessionRepository, session_id: str, extractor: Extractor, labeler: SpeakerLabeler
) -> list[ActionItem]:
    """Extract from the best transcript and save; returns every stored item.

    Items already exported are kept (so they are never exported twice) and the new ones follow
    with ids that do not collide with theirs. Language, glossary and meeting date come from
    `session.json`. Raises `SessionNotFoundError`, `EmptyTranscriptError` or
    `LanguageModelError`; on failure nothing is written.
    """
    meta = store.read_meta(session_id)
    segments = store.load_transcript(session_id)
    if not segments:
        raise EmptyTranscriptError(session_id)
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    named = labeler.with_names(store.speaker_names(session_id))
    fresh = extractor.extract(
        segments, named, language, stored_vocabulary(meta), _meeting_date(meta)
    )
    with store.action_items_lock():
        kept = [item for item in store.read_action_items(session_id) if item.exported_url]
        items = kept + _renumber(fresh, {item.id for item in kept})
        store.write_action_items(session_id, items)
    return items


def _renumber(items: list[ActionItem], taken: set[str]) -> list[ActionItem]:
    renumbered: list[ActionItem] = []
    number = 0
    for item in items:
        number += 1
        while f"a{number}" in taken:
            number += 1
        renumbered.append(
            ActionItem(
                f"a{number}", item.description, item.owner, item.due, item.source_segment_ids
            )
        )
    return renumbered


def _meeting_date(meta: dict[str, Any]) -> str | None:
    started = meta.get("started_at")
    return started[:10] if isinstance(started, str) and len(started) >= 10 else None
