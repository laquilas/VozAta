from __future__ import annotations

import pytest

from vozata.config import Settings
from vozata.domain import AppLanguage, ConversationLanguage
from vozata.language import resolve_conversation_language, to_whisper_code


def test_without_a_request_the_configured_language_is_used() -> None:
    settings = Settings(transcription_language=ConversationLanguage.ES)

    assert resolve_conversation_language(settings, None) is ConversationLanguage.ES
    assert resolve_conversation_language(settings, "  ") is ConversationLanguage.ES


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("pt", ConversationLanguage.PT),
        ("pt-BR", ConversationLanguage.PT),
        ("EN", ConversationLanguage.EN),
        ("es", ConversationLanguage.ES),
        ("auto", ConversationLanguage.AUTO),
    ],
)
def test_requested_language_wins_and_is_normalized(
    requested: str, expected: ConversationLanguage
) -> None:
    settings = Settings(app_language=AppLanguage.EN)

    assert resolve_conversation_language(settings, requested) is expected


def test_unsupported_requested_language_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_conversation_language(Settings(), "fr")


@pytest.mark.parametrize(
    ("language", "code"),
    [
        (ConversationLanguage.EN, "en"),
        (ConversationLanguage.PT, "pt"),
        (ConversationLanguage.ES, "es"),
        (ConversationLanguage.AUTO, None),
    ],
)
def test_to_whisper_code(language: ConversationLanguage, code: str | None) -> None:
    assert to_whisper_code(language) == code
