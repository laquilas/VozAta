"""The meeting title in the minutes prompts (phase 35)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.domain import AppLanguage, Channel, ConversationLanguage, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.minutes.session_minutes import write_session_minutes
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

TITLES = {
    AppLanguage.EN: 'The user titled this meeting "Budget 2027".',
    AppLanguage.PT_BR: 'O usuário deu a esta reunião o título "Budget 2027".',
    AppLanguage.ES: 'El usuario tituló esta reunión "Budget 2027".',
}


@pytest.mark.parametrize("language", list(AppLanguage))
def test_every_prompt_gets_the_title_in_every_language(language: AppLanguage) -> None:
    localizer = TomlLocalizer(language, strict=True)
    template = minutes_template(language.value)
    title = "Budget 2027"

    prompts = [
        minutes_prompt(localizer, template, "x", ConversationLanguage.EN, title=title),
        map_prompt(localizer, template, "x", 1, 2, ConversationLanguage.EN, title=title),
        reduce_prompt(localizer, template, ["n"], ConversationLanguage.EN, title=title),
    ]

    for _, user in prompts:
        assert TITLES[language] in user
        assert "{" not in user


@pytest.mark.parametrize("title", [None, ""])
def test_an_untitled_meeting_adds_no_title_line(title: str | None) -> None:
    localizer = FakeLocalizer()

    _, user = minutes_prompt(
        localizer, minutes_template(), "x", ConversationLanguage.EN, title=title
    )

    assert "minutes.meeting_title" not in user


def test_the_title_comes_before_the_glossary_and_the_transcript() -> None:
    _, user = minutes_prompt(
        FakeLocalizer(),
        minutes_template(),
        "[00:00:01] Me: hi",
        ConversationLanguage.EN,
        ["VozAta"],
        "Kickoff",
    )

    title_at = user.index("minutes.meeting_title(title=Kickoff)")
    assert title_at < user.index("minutes.glossary(terms=VozAta)")
    assert title_at < user.index("[00:00:01] Me: hi")


def _segment(start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        f"mic-{int(start):06d}", Channel.MIC, "mic", start, start + 1, text, ()
    )


def test_the_generator_passes_the_title_to_every_long_meeting_step() -> None:
    llm = FakeLanguageModel(replies=["notes 1", "notes 2", "# Minutes"])
    generator = MinutesGenerator(llm, FakeLocalizer(), 40, minutes_template())
    segments = [_segment(1, "a" * 30), _segment(2, "b" * 30)]

    generator.generate(
        segments, SpeakerLabeler(FakeLocalizer()), ConversationLanguage.EN, title="Retro"
    )

    assert len(llm.prompts) == 3
    assert all("minutes.meeting_title(title=Retro)" in user for _, user, _ in llm.prompts)


def test_regenerated_minutes_use_the_stored_title(tmp_path: Path) -> None:
    store = FileSessionRepository(SessionStore(tmp_path))
    session_id = store.create()
    store.write_meta(session_id, {"id": session_id, "status": "done", "title": "Retro"})
    sink = store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    sink.emit(_segment(1, "Hello."))
    sink.close()
    llm = FakeLanguageModel(replies=["# Minutes"])

    write_session_minutes(
        store,
        session_id,
        lambda template: MinutesGenerator(llm, FakeLocalizer(), 12000, minutes_template()),
        SpeakerLabeler(FakeLocalizer()),
    )

    assert "minutes.meeting_title(title=Retro)" in llm.prompts[0][1]
