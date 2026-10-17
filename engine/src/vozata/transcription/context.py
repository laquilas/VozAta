"""Rolling context prompt for one channel (phase 19, optimizations.md O4).

Whisper keeps names, spelling and punctuation consistent when it sees the preceding text, but
VozAta transcribes independent chunks. The last committed text of the channel is passed as the
prompt of the next transcription (`condition_on_previous_text` stays off). Guards against Whisper's
repetition loops: the prompt is cleared when the conversation language changes (it locks) or after
a long silence, and skipped for the next chunk after a repeated segment or a very low
`avg_logprob`.
"""

from __future__ import annotations

import re

LONG_SILENCE_SECONDS = 30.0  # a pause this long usually starts another topic
LOW_AVG_LOGPROB = -1.0  # Whisper's own "this is probably garbage" threshold
_SPACES = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[^\w\s]")


class RollingContext:
    """The last `max_chars` of committed text, cut on a word boundary; `max_chars=0` turns it off.

    `prompt()` only peeks; `take(at)` is used for the transcription that may commit text and
    consumes a pending skip.
    """

    def __init__(
        self,
        max_chars: int,
        long_silence_seconds: float = LONG_SILENCE_SECONDS,
        low_avg_logprob: float = LOW_AVG_LOGPROB,
    ) -> None:
        self._max = max_chars
        self._silence = long_silence_seconds
        self._low = low_avg_logprob
        self._text = ""
        self._last_segment = ""
        self._last_end: float | None = None
        self._skip = False
        self._language: str | None = None

    def prompt(self) -> str | None:
        """The prompt for the next transcription; None when off, empty or skipped."""
        if self._max <= 0 or self._skip or not self._text:
            return None
        return self._text

    def take(self, at: float) -> str | None:
        """The prompt for audio starting at `at` (session seconds); clears a pending skip."""
        if self._last_end is not None and at - self._last_end >= self._silence:
            self.clear()
        prompt = self.prompt()
        self._skip = False
        return prompt

    def language(self, current: str | None) -> None:
        """Clear the context when the transcription language changes (e.g. `auto` locks)."""
        if current != self._language:
            self._language = current
            self.clear()

    def observe(self, avg_logprob: float | None) -> None:
        """Skip the prompt for the next chunk after a very unsure transcription."""
        if avg_logprob is not None and avg_logprob < self._low:
            self._skip = True

    def commit(self, text: str, end: float) -> None:
        """Append a committed segment; a segment repeating the previous one is not appended and
        the next chunk is transcribed without a prompt."""
        self._last_end = end
        key = _key(text)
        if not key:
            return
        if key == self._last_segment:
            self._skip = True
            return
        self._last_segment = key
        if self._max > 0:
            self._text = _tail(f"{self._text} {text}", self._max)

    def clear(self) -> None:
        self._text = ""
        self._last_segment = ""
        self._skip = False


def _key(text: str) -> str:
    return _SPACES.sub(" ", _NOT_WORD.sub("", text.casefold())).strip()


def _tail(text: str, max_chars: int) -> str:
    """The last `max_chars` characters of `text`, starting at a word boundary."""
    text = _SPACES.sub(" ", text).strip()
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    if text[-max_chars - 1] != " ":
        space = tail.find(" ")
        tail = tail[space + 1 :] if space >= 0 else ""
    return tail.strip()
