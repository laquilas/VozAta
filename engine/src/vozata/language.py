"""Conversation (spoken) language resolution (architecture §10)."""

from __future__ import annotations

from vozata.config import Settings
from vozata.domain import ConversationLanguage


def resolve_conversation_language(
    settings: Settings, requested: str | None
) -> ConversationLanguage:
    """The language for one session: the request if given, else the configured default.

    Requests are normalized (`pt-BR` -> `pt`, case-insensitive); unsupported values raise
    `ValueError`.
    """
    if requested is None or not requested.strip():
        return settings.transcription_language
    code = requested.strip().lower().split("-")[0]
    return ConversationLanguage(code)


def to_whisper_code(language: ConversationLanguage) -> str | None:
    """The Whisper `language` argument; `None` lets Whisper detect it (`auto`)."""
    return None if language is ConversationLanguage.AUTO else language.value
