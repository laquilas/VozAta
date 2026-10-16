from __future__ import annotations

import pytest

from vozata.domain import ConversationLanguage
from vozata.transcription.language_lock import LanguageLock


@pytest.fixture
def detected() -> list[ConversationLanguage]:
    return []


@pytest.mark.parametrize(
    ("language", "code"),
    [
        (ConversationLanguage.EN, "en"),
        (ConversationLanguage.PT, "pt"),
        (ConversationLanguage.ES, "es"),
    ],
)
def test_fixed_language_passes_through(
    language: ConversationLanguage, code: str, detected: list[ConversationLanguage]
) -> None:
    lock = LanguageLock(language, detected.append)

    lock.observe("es", 10.0)

    assert lock.current() == code
    assert detected == []


def test_auto_lets_whisper_detect_until_enough_speech(detected: list[ConversationLanguage]) -> None:
    lock = LanguageLock(ConversationLanguage.AUTO, detected.append)

    lock.observe("pt", 2.9)

    assert lock.current() is None
    assert detected == []


def test_auto_locks_on_the_majority_after_three_seconds(
    detected: list[ConversationLanguage],
) -> None:
    lock = LanguageLock(ConversationLanguage.AUTO, detected.append)

    lock.observe("pt", 1.0)
    lock.observe("es", 0.5)
    lock.observe("pt", 1.5)

    assert lock.current() == "pt"
    assert lock.language is ConversationLanguage.PT
    assert detected == [ConversationLanguage.PT]


def test_callback_fires_once(detected: list[ConversationLanguage]) -> None:
    lock = LanguageLock(ConversationLanguage.AUTO, detected.append)

    lock.observe("en", 5.0)
    lock.observe("es", 50.0)

    assert lock.current() == "en"
    assert detected == [ConversationLanguage.EN]


@pytest.mark.parametrize("language", ["fr", None])
def test_unsupported_or_missing_languages_do_not_count(
    language: str | None, detected: list[ConversationLanguage]
) -> None:
    lock = LanguageLock(ConversationLanguage.AUTO, detected.append)

    lock.observe(language, 10.0)

    assert lock.current() is None
    assert lock.language is ConversationLanguage.AUTO
