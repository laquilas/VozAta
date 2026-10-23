"""Voice commands in the composition root and the session (phase 50)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes import FakeSessionObserver
from tests.test_bootstrap import devices  # noqa: F401 - the fixture
from vozata import bootstrap
from vozata.commands.detector import VoiceCommandSink
from vozata.config import Settings
from vozata.domain import Channel, TranscriptSegment, VoiceCommand


class _Heard:
    """A `VoiceDispatch` that records the commands (phase 59: with their second)."""

    def __init__(self, heard: list[tuple[str, VoiceCommand]]) -> None:
        self.heard = heard
        self.repeats: list[tuple[str, VoiceCommand, float | None]] = []

    def __call__(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None:
        self.heard.append((session_id, command))

    def repeated(self, session_id: str, command: VoiceCommand, at: float | None = None) -> None:
        self.repeats.append((session_id, command, at))


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def _segment(text: str) -> TranscriptSegment:
    return TranscriptSegment("mic-000001", Channel.MIC, "mic", 1, 3, text, ())


def test_a_session_listens_with_the_saved_phrases_and_the_wake_word_leads_the_hints(
    tmp_path: Path,
    devices: list[int],  # noqa: F811
) -> None:
    (tmp_path / "voice_commands.json").write_text(
        json.dumps({"commands": [{"phrase": "resume", "action": "minutes", "question": None}]}),
        encoding="utf-8",
    )
    heard: list[tuple[str, VoiceCommand]] = []

    session = bootstrap.build_session(
        _settings(tmp_path, wake_word="Atena"),
        FakeSessionObserver(),
        vocabulary=["Kickoff"],
        env_file=tmp_path / ".env",
        voice_dispatch=(dispatch := _Heard(heard)),
    )

    assert session._c.vocabulary[:2] == ("Atena", "Kickoff")
    factory = session._c.voice_commands
    assert factory is not None
    sink = factory("s1")
    assert isinstance(sink, VoiceCommandSink)
    sink.emit(_segment("Atena, resume."))
    assert heard == [("s1", VoiceCommand("resume", "minutes"))]
    sink.emit(_segment("Atena, resume."))  # phase 59: again within the cooldown
    assert [(sid, command) for sid, command, _ in dispatch.repeats] == [
        ("s1", VoiceCommand("resume", "minutes"))
    ]


@pytest.mark.parametrize(("enabled", "dispatch"), [(False, True), (True, False)])
def test_without_commands_nothing_listens(
    tmp_path: Path,
    devices: list[int],  # noqa: F811
    enabled: bool,
    dispatch: bool,
) -> None:
    session = bootstrap.build_session(
        _settings(tmp_path, voice_commands_enabled=enabled),
        FakeSessionObserver(),
        voice_dispatch=_Heard([]) if dispatch else None,
    )

    assert session._c.voice_commands is None
    assert "VozAta" not in session._c.vocabulary


def test_the_prompts_leave_out_what_was_said_to_vozata(tmp_path: Path) -> None:
    keep = bootstrap.command_filter(_settings(tmp_path, voice_commands_file=tmp_path / "none.json"))

    assert keep is not None
    assert keep(_segment("VozAta, make the minutes.")) is True
    assert keep(_segment("We make the minutes later.")) is False
    assert bootstrap.command_filter(_settings(tmp_path, voice_commands_enabled=False)) is None


def test_the_generators_get_the_filter(tmp_path: Path) -> None:
    settings = _settings(tmp_path, voice_commands_file=tmp_path / "none.json")

    generator = bootstrap.build_minutes_generator(settings)
    extractor = bootstrap.build_action_item_extractor(settings)

    assert generator._exclude is not None and extractor._exclude is not None


def test_the_command_file_lives_next_to_the_settings(tmp_path: Path) -> None:
    assert (
        bootstrap.voice_commands_path(Settings(), tmp_path / ".env")
        == tmp_path / "voice_commands.json"
    )
    custom = tmp_path / "x.json"
    assert bootstrap.voice_commands_path(Settings(voice_commands_file=custom)) == custom
