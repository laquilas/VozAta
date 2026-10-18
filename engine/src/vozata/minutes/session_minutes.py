"""(Re)generate a stored session's minutes (CLI `minutes` command, `POST .../minutes`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vozata.domain import ConversationLanguage
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.template_repository import bundled_templates
from vozata.ports import SessionRepository
from vozata.session_title import stored_title

GeneratorFactory = Callable[[str | None], MinutesGenerator]  # template id; None = the default


class EmptyTranscriptError(ValueError):
    """The session has no transcript, so there is nothing to summarize."""


def write_session_minutes(
    store: SessionRepository,
    session_id: str,
    build_generator: GeneratorFactory,
    labeler: SpeakerLabeler,
    template: str | None = None,
) -> None:
    """Minutes from the best transcript, in the language stored in `session.json` (else `auto`).

    The glossary is the `vocabulary` stored in `session.json` (phase 19). The template is
    `template`, else the one stored in the metadata (when still bundled), else the default;
    the one used is saved back to the metadata. Raises `SessionNotFoundError`,
    `EmptyTranscriptError` or `LanguageModelError`; on failure nothing is written.
    """
    meta = store.read_meta(session_id)
    segments = store.load_transcript(session_id)
    if not segments:
        raise EmptyTranscriptError(session_id)
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    named = labeler.with_names(store.speaker_names(session_id))
    generator = build_generator(template or stored_template(meta))
    minutes = generator.generate(
        segments, named, language, stored_vocabulary(meta), stored_title(meta)
    )
    store.write_minutes(session_id, minutes + "\n")
    if meta.get("template") != generator.template_id:
        latest = store.read_meta(session_id)
        store.write_meta(session_id, {**latest, "template": generator.template_id})


def stored_vocabulary(meta: dict[str, Any]) -> list[str]:
    """The glossary terms saved in `session.json` (phase 19); empty when absent or invalid."""
    stored = meta.get("vocabulary")
    if not isinstance(stored, list):
        return []
    return [term for term in stored if isinstance(term, str) and term.strip()]


def stored_template(meta: dict[str, Any]) -> str | None:
    """The template saved in `session.json` (phase 20) when still bundled, else None."""
    stored = meta.get("template")
    return stored if isinstance(stored, str) and stored in bundled_templates() else None
