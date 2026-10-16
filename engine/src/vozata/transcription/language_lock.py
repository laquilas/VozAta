"""Conversation-language lock for `auto` mode (architecture §10)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from vozata.domain import ConversationLanguage

_DETECTABLE = {language.value for language in ConversationLanguage} - {"auto"}


class LanguageLock:
    """The Whisper language code to use for a session.

    A fixed language passes through. In `auto`, Whisper detects per window (`current()` is None)
    until `min_speech_seconds` of speech in supported languages were observed; the majority
    language is then locked for the rest of the session and `on_detected` fires once.
    """

    def __init__(
        self,
        initial: ConversationLanguage,
        on_detected: Callable[[ConversationLanguage], None],
        min_speech_seconds: float = 3.0,
    ) -> None:
        self.language = initial
        self._on_detected = on_detected
        self._min_speech = min_speech_seconds
        self._seconds: Counter[str] = Counter()

    def current(self) -> str | None:
        return None if self.language is ConversationLanguage.AUTO else self.language.value

    def observe(self, language: str | None, speech_seconds: float) -> None:
        if self.language is not ConversationLanguage.AUTO or language not in _DETECTABLE:
            return
        self._seconds[language] += speech_seconds
        if self._seconds.total() >= self._min_speech:
            self.language = ConversationLanguage(self._seconds.most_common(1)[0][0])
            self._on_detected(self.language)
