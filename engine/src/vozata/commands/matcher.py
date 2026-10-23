"""Find "<wake word>, <command phrase>" in transcribed speech (phase 50).

Speech recognition spells a made-up word several ways ("VozAta", "Voz Ata", "vozata,"), so the
text is normalized (casefold, no accents, words only) and compared with `difflib` ratios rather
than exactly.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence

from vozata.domain import VoiceCommand

WAKE_RATIO = 0.8
PHRASE_RATIO = 0.75
_WORD = re.compile(r"\w+")


def words(text: str) -> list[str]:
    """Casefolded words without accents ("Gere a ATA!" -> ["gere", "a", "ata"])."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return _WORD.findall(plain)


def _ratio(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left, right).ratio()


class CommandMatcher:
    """`wake_word` then one of `commands`, said in one breath or split over two segments."""

    def __init__(self, wake_word: str, commands: Sequence[VoiceCommand]) -> None:
        self._wake = "".join(words(wake_word))
        self._commands = [(command, words(command.phrase)) for command in commands]

    def after_wake(self, text: str) -> list[str] | None:
        """The words after the wake word (empty when it ends the text), or None without it."""
        found = words(text)
        if not self._wake:
            return None
        for index in range(len(found)):
            for span in (1, 2):  # "vozata" or "voz ata"
                joined = "".join(found[index : index + span])
                if index + span <= len(found) and _ratio(joined, self._wake) >= WAKE_RATIO:
                    return found[index + span :]
        return None

    def command(self, spoken: Sequence[str]) -> VoiceCommand | None:
        """The command whose phrase best matches the first words of `spoken`."""
        best: tuple[float, VoiceCommand] | None = None
        for command, phrase in self._commands:
            if not phrase:
                continue
            for size in range(max(1, len(phrase) - 1), len(phrase) + 2):
                if size > len(spoken):
                    break
                score = _ratio(" ".join(spoken[:size]), " ".join(phrase))
                if score >= PHRASE_RATIO and (best is None or score > best[0]):
                    best = (score, command)
        return best[1] if best is not None else None

    def find(self, text: str) -> VoiceCommand | None:
        """The command said in `text` after the wake word, if any."""
        spoken = self.after_wake(text)
        return self.command(spoken) if spoken else None

    def addressed(self, text: str) -> bool:
        """`text` is a command to VozAta (kept in the transcript, left out of the prompts)."""
        return self.find(text) is not None
