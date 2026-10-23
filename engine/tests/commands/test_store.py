from __future__ import annotations

import json
from pathlib import Path

import pytest

from vozata.commands.store import (
    MAX_COMMANDS,
    InvalidCommandsError,
    VoiceCommandStore,
    default_commands,
    validate,
)
from vozata.domain import AppLanguage, VoiceCommand
from vozata.i18n import TomlLocalizer


@pytest.mark.parametrize("language", list(AppLanguage))
def test_every_language_has_three_default_commands(language: AppLanguage) -> None:
    defaults = default_commands(TomlLocalizer(language, strict=True))

    assert [command.action for command in defaults] == ["minutes", "ask", "ask"]
    assert all(command.phrase for command in defaults)
    assert defaults[0].question is None and all(command.question for command in defaults[1:])


def test_portuguese_defaults() -> None:
    first = default_commands(TomlLocalizer(AppLanguage.PT_BR))[0]

    assert first == VoiceCommand("gere a ata", "minutes")


def test_without_a_file_the_defaults_are_used_and_a_saved_list_wins(tmp_path: Path) -> None:
    localizer = TomlLocalizer(AppLanguage.EN)
    store = VoiceCommandStore(tmp_path / "sub" / "voice_commands.json", localizer)
    assert store.read() == default_commands(localizer)

    saved = store.write([VoiceCommand("  summary please ", "minutes", "ignored")])

    assert saved == [VoiceCommand("summary please", "minutes")]
    assert store.read() == saved
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data == {
        "schema_version": 1,
        "commands": [{"phrase": "summary please", "action": "minutes", "question": None}],
    }


def test_an_unreadable_file_falls_back_to_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "voice_commands.json"
    path.write_text("{broken", encoding="utf-8")
    localizer = TomlLocalizer(AppLanguage.ES)

    assert VoiceCommandStore(path, localizer).read() == default_commands(localizer)


@pytest.mark.parametrize(
    "commands",
    [
        [VoiceCommand(" ", "minutes")],
        [VoiceCommand("x" * 81, "minutes")],
        [VoiceCommand("stop", "pause")],
        [VoiceCommand("what now", "ask")],
        [VoiceCommand("what now", "ask", "q" * 301)],
        [VoiceCommand(f"c{i}", "minutes") for i in range(MAX_COMMANDS + 1)],
    ],
)
def test_invalid_lists_are_refused(commands: list[VoiceCommand]) -> None:
    with pytest.raises(InvalidCommandsError):
        validate(commands)
