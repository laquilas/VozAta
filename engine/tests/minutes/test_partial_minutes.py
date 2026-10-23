"""Minutes of part of a meeting (phase 48)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.domain import (
    AppLanguage,
    Channel,
    ConversationLanguage,
    PartialMinutes,
    TranscriptSegment,
)
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.partial_minutes import (
    delete_partial_minutes,
    segments_in_range,
    write_partial_minutes,
)
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.minutes.session_minutes import EmptyTranscriptError
from vozata.ports import LanguageModelError
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

NOW = datetime(2026, 10, 22, 13, 5, tzinfo=UTC)


def _segment(start: float, text: str, speaker: str = "mic") -> TranscriptSegment:
    channel = Channel.SYSTEM if speaker.startswith("system") else Channel.MIC
    return TranscriptSegment(
        f"{channel.value}-{int(start):06d}", channel, speaker, start, start + 2, text, ()
    )


SEGMENTS = [_segment(10, "Olá."), _segment(152, "Decidimos adiar."), _segment(700, "Fim.")]


@pytest.mark.parametrize(
    ("start", "end", "kept"),
    [
        (0, None, [10, 152, 700]),
        (152, 700, [152]),  # a segment starting exactly at the end is out
        (11, 152, []),
        (701, None, []),
    ],
)
def test_a_segment_belongs_to_the_range_it_starts_in(
    start: float, end: float | None, kept: list[float]
) -> None:
    assert [segment.start for segment in segments_in_range(SEGMENTS, start, end)] == kept


def _store(
    tmp_path: Path, meta: dict[str, object] | None = None
) -> tuple[FileSessionRepository, str]:
    store = FileSessionRepository(SessionStore(tmp_path))
    session_id = store.create()
    store.write_meta(session_id, {"id": session_id, "status": "recording", **(meta or {})})
    sink = store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for segment in SEGMENTS:
        sink.emit(segment)
    sink.close()
    store.rename_speakers(session_id, {"mic": "Ana"})
    return store, session_id


def _write(
    store: FileSessionRepository,
    session_id: str,
    llm: FakeLanguageModel,
    built: list[str | None] | None = None,
    **options: object,
) -> PartialMinutes:
    def build(template: str | None) -> MinutesGenerator:
        if built is not None:
            built.append(template)
        return MinutesGenerator(
            llm, FakeLocalizer(), 12000, minutes_template(template_id=template or "general")
        )

    values: dict[str, object] = {"start": 0.0, "end": None, "origin": "button", "live": True}
    values.update(options)
    return write_partial_minutes(
        store,
        session_id,
        build,
        SpeakerLabeler(FakeLocalizer()),
        FakeLocalizer(),
        new_id=lambda: "p1",
        now=lambda: NOW,
        **values,  # type: ignore[arg-type]
    )


def test_minutes_so_far_cover_everything_stored_and_say_the_meeting_goes_on(tmp_path: Path) -> None:
    store, session_id = _store(
        tmp_path,
        {
            "language": "pt",
            "title": "Planejamento",
            "vocabulary": ["VozAta"],
            "template": "retrospective",
        },
    )
    llm = FakeLanguageModel(replies=["# Até agora"])
    built: list[str | None] = []

    item = _write(store, session_id, llm, built)

    assert item == PartialMinutes(
        "p1", "2026-10-22T13:05:00+00:00", 0.0, 702.0, "button", "# Até agora\n", "retrospective"
    )
    assert built == ["retrospective"]
    _, user, _ = llm.prompts[0]
    assert "minutes.scope_live(end=00:11:42)" in user
    assert "minutes.meeting_title(title=Planejamento)" in user
    assert "minutes.glossary(terms=VozAta)" in user
    assert "Ana: Olá." in user and "Fim." in user
    assert store.read_partial_minutes(session_id) == [item]
    assert store.read_minutes(session_id) is None  # the final minutes are not touched


def test_minutes_of_a_range_say_which_part_and_keep_the_others(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path)
    first = _write(store, session_id, FakeLanguageModel(replies=["# A"]))
    llm = FakeLanguageModel(replies=["# Trecho"])

    item = write_partial_minutes(
        store,
        session_id,
        lambda template: MinutesGenerator(llm, FakeLocalizer(), 12000, minutes_template()),
        SpeakerLabeler(FakeLocalizer()),
        FakeLocalizer(),
        start=152.0,
        end=774.0,
        origin="range",
        live=False,
        template="general",
        new_id=lambda: "p2",
        now=lambda: NOW,
    )

    _, user, _ = llm.prompts[0]
    assert "minutes.scope_range(end=00:12:54,start=00:02:32)" in user
    assert "Decidimos adiar." in user and "Olá." not in user and "Fim." in user
    assert (item.start, item.end, item.origin) == (152.0, 774.0, "range")
    assert store.read_partial_minutes(session_id) == [first, item]


def test_an_empty_range_writes_nothing(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path)
    llm = FakeLanguageModel(replies=["# x"])

    with pytest.raises(EmptyTranscriptError):
        _write(store, session_id, llm, start=11.0, end=150.0, live=False)

    assert llm.prompts == []
    assert store.read_partial_minutes(session_id) == []


def test_a_failing_model_writes_nothing(tmp_path: Path) -> None:
    class _Failing(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            raise LanguageModelError("offline")

    store, session_id = _store(tmp_path)

    with pytest.raises(LanguageModelError):
        _write(store, session_id, _Failing())

    assert store.read_partial_minutes(session_id) == []


def test_deleting_one_keeps_the_others(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path)
    kept = PartialMinutes("a", "t", 0, 1, "button", "# A\n")
    store.write_partial_minutes(
        session_id, [kept, PartialMinutes("b", "t", 0, 2, "voice", "# B\n")]
    )

    assert delete_partial_minutes(store, session_id, "b") is True
    assert delete_partial_minutes(store, session_id, "missing") is False
    assert store.read_partial_minutes(session_id) == [kept]


@pytest.mark.parametrize("language", list(AppLanguage))
def test_every_prompt_carries_the_scope_line_in_every_language(language: AppLanguage) -> None:
    localizer = TomlLocalizer(language, strict=True)
    template = minutes_template(language.value)
    scope = localizer.t("minutes.scope_range", start="00:02:32", end="00:12:54")

    prompts = [
        minutes_prompt(localizer, template, "x", ConversationLanguage.EN, scope=scope),
        map_prompt(localizer, template, "x", 1, 2, ConversationLanguage.EN, scope=scope),
        reduce_prompt(localizer, template, ["n"], ConversationLanguage.EN, scope=scope),
    ]

    assert "00:12:54" in localizer.t("minutes.scope_live", end="00:12:54")
    for _, user in prompts:
        assert scope in user and "00:02:32" in user


def test_whole_meeting_minutes_have_no_scope_line() -> None:
    _, user = minutes_prompt(FakeLocalizer(), minutes_template(), "x", ConversationLanguage.EN)

    assert "minutes.scope" not in user
