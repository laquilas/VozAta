"""The voice command list (phase 50): a JSON file, or the defaults of the app language."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from vozata.domain import VoiceCommand
from vozata.ports import Localizer

SCHEMA_VERSION = 1
MAX_COMMANDS = 30
MAX_PHRASE = 80
MAX_QUESTION = 300
ACTIONS = ("minutes", "ask")

_log = logging.getLogger(__name__)


class InvalidCommandsError(ValueError):
    """A list that cannot be saved; the message says which entry and why."""


def default_commands(localizer: Localizer) -> list[VoiceCommand]:
    """Minutes so far, what was decided and the next steps, in the app language."""
    t = localizer.t
    return [
        VoiceCommand(t("voice_commands.minutes_phrase"), "minutes"),
        VoiceCommand(
            t("voice_commands.decided_phrase"), "ask", t("voice_commands.decided_question")
        ),
        VoiceCommand(t("voice_commands.next_phrase"), "ask", t("voice_commands.next_question")),
    ]


def validate(commands: Sequence[VoiceCommand]) -> list[VoiceCommand]:
    """Trimmed commands; raises `InvalidCommandsError`."""
    if len(commands) > MAX_COMMANDS:
        raise InvalidCommandsError(f"at most {MAX_COMMANDS} commands")
    cleaned = []
    for index, command in enumerate(commands, start=1):
        phrase = command.phrase.strip()
        question = (command.question or "").strip() or None
        if not phrase or len(phrase) > MAX_PHRASE:
            raise InvalidCommandsError(
                f"command {index}: the phrase needs 1 to {MAX_PHRASE} characters"
            )
        if command.action not in ACTIONS:
            raise InvalidCommandsError(
                f"command {index}: the action must be one of {', '.join(ACTIONS)}"
            )
        if command.action == "ask" and (question is None or len(question) > MAX_QUESTION):
            raise InvalidCommandsError(
                f"command {index}: a question needs 1 to {MAX_QUESTION} characters"
            )
        cleaned.append(
            VoiceCommand(phrase, command.action, question if command.action == "ask" else None)
        )
    return cleaned


class VoiceCommandStore:
    def __init__(self, path: Path, localizer: Localizer) -> None:
        self.path = path
        self._localizer = localizer

    def read(self) -> list[VoiceCommand]:
        """The saved list; the defaults when there is no file or it is unreadable."""
        if not self.path.is_file():
            return default_commands(self._localizer)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return validate([VoiceCommand.from_dict(item) for item in data["commands"]])
        except (OSError, ValueError, KeyError, TypeError) as error:
            _log.warning("Ignoring unreadable %s: %s", self.path, error)
            return default_commands(self._localizer)

    def write(self, commands: Sequence[VoiceCommand]) -> list[VoiceCommand]:
        """Validate and save; raises `InvalidCommandsError` or `OSError`."""
        cleaned = validate(commands)
        data = {"schema_version": SCHEMA_VERSION, "commands": [c.to_dict() for c in cleaned]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return cleaned
