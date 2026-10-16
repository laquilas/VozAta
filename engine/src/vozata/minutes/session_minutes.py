"""(Re)generate a stored session's `minutes.md` (CLI `minutes` command, `POST .../minutes`)."""

from __future__ import annotations

from pathlib import Path

from vozata.domain import ConversationLanguage
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.storage.session_store import SessionStore


class EmptyTranscriptError(ValueError):
    """The session has no transcript, so there is nothing to summarize."""


def write_session_minutes(
    store: SessionStore,
    session_id: str,
    generator: MinutesGenerator,
    labeler: SpeakerLabeler,
) -> Path:
    """Minutes from the best transcript, in the language stored in `session.json` (else `auto`).

    Raises `SessionNotFoundError`, `EmptyTranscriptError` or `LanguageModelError`; on failure
    nothing is written.
    """
    meta = store.read_meta(session_id)
    segments = store.load_transcript(session_id)
    if not segments:
        raise EmptyTranscriptError(session_id)
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    minutes = generator.generate(segments, labeler, language)
    path = store.paths(session_id).minutes_md
    path.write_text(minutes + "\n", encoding="utf-8", newline="\n")
    return path
