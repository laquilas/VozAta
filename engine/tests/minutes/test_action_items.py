from __future__ import annotations

import json

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.domain import ActionItem, AppLanguage, Channel, ConversationLanguage, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.minutes.action_items import (
    SCHEMA,
    ActionItemExtractor,
    ActionItemsError,
    InvalidReplyError,
    parse_reply,
)
from vozata.ports import LanguageModelError

EN = ConversationLanguage.EN


def _segment(number: int, text: str, start: float) -> TranscriptSegment:
    return TranscriptSegment(f"mic-{number:06d}", Channel.MIC, "mic", start, start + 1, text, ())


SEGMENTS = [
    _segment(2, "Ana will send the report by Friday.", 65.0),
    _segment(1, "Let us start.", 1.0),
]


def _reply(*items: dict) -> str:
    return json.dumps({"items": list(items)})


ITEM = {
    "description": "Send the report",
    "owner": "Ana",
    "due": "2026-10-16",
    "source_segment_ids": ["mic-000002", "mic-999999"],
}


def _extractor(llm: FakeLanguageModel, max_chars: int = 12000) -> ActionItemExtractor:
    return ActionItemExtractor(llm, TomlLocalizer(AppLanguage.EN), max_chars)


def _labeler() -> SpeakerLabeler:
    return SpeakerLabeler(TomlLocalizer(AppLanguage.EN))


def test_valid_reply_becomes_numbered_items_linked_to_known_segments() -> None:
    llm = FakeLanguageModel([_reply(ITEM, {"description": " Book room ", "owner": ""})])

    items = _extractor(llm).extract(SEGMENTS, _labeler(), EN)

    assert items == [
        ActionItem("a1", "Send the report", "Ana", "2026-10-16", ("mic-000002",)),
        ActionItem("a2", "Book room", None, None, ()),
    ]
    [(system, user, schema)] = llm.prompts
    assert schema == SCHEMA
    assert "action items" in system
    assert user.index("[mic-000001] [00:00:01] Me: Let us start.") < user.index(
        "[mic-000002] [00:01:05] Me: Ana will send"
    )
    assert llm.releases == 1


def test_an_invalid_reply_is_retried_once() -> None:
    llm = FakeLanguageModel(["not json", _reply(ITEM)])

    items = _extractor(llm).extract(SEGMENTS, _labeler(), EN)

    assert [item.description for item in items] == ["Send the report"]
    assert len(llm.prompts) == 2


def test_two_invalid_replies_raise_and_still_release_the_model() -> None:
    llm = FakeLanguageModel(['{"items": "none"}', "[]"])

    with pytest.raises(ActionItemsError, match="valid action items"):
        _extractor(llm).extract(SEGMENTS, _labeler(), EN)

    assert len(llm.prompts) == 2
    assert llm.releases == 1
    assert issubclass(ActionItemsError, LanguageModelError)


def test_a_model_failure_propagates_after_release() -> None:
    class Failing(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            raise LanguageModelError("Ollama is down")

    llm = Failing()
    with pytest.raises(LanguageModelError, match="down"):
        _extractor(llm).extract(SEGMENTS, _labeler(), EN)
    assert llm.releases == 1


def test_a_failed_release_is_only_logged() -> None:
    class StuckRelease(FakeLanguageModel):
        def release(self) -> None:
            raise LanguageModelError("busy")

    assert _extractor(StuckRelease([_reply()])).extract(SEGMENTS, _labeler(), EN) == []


def test_a_long_transcript_is_split_and_items_are_concatenated() -> None:
    llm = FakeLanguageModel([_reply(ITEM), _reply({**ITEM, "description": "Second"})])

    items = _extractor(llm, max_chars=60).extract(SEGMENTS, _labeler(), EN)

    assert [(item.id, item.description) for item in items] == [
        ("a1", "Send the report"),
        ("a2", "Second"),
    ]
    assert "part 1 of 2" in llm.prompts[0][1]
    assert "part 2 of 2" in llm.prompts[1][1]


def test_an_empty_transcript_asks_nothing() -> None:
    llm = FakeLanguageModel()
    assert _extractor(llm).extract([], _labeler(), EN) == []
    assert llm.prompts == []


def test_prompt_has_languages_date_and_glossary_only_when_given() -> None:
    extractor = ActionItemExtractor(FakeLanguageModel(), FakeLocalizer(), 100)

    system, user = extractor.prompt(
        "lines", 1, 1, ConversationLanguage.PT, ["Avalonia"], "2026-10-15"
    )
    _, bare = extractor.prompt("lines", 1, 1, EN)

    assert system == "action_items.system"
    assert "conversation_language=languages.pt" in user
    assert "action_items.meeting_date(date=2026-10-15)" in user
    assert "minutes.glossary(terms=Avalonia)" in user
    assert user.endswith("action_items.transcript_label\nlines")
    assert "meeting_date" not in bare
    assert "glossary" not in bare
    assert "action_items.part" not in bare


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("{", "not JSON"),
        ('["a"]', "items"),
        ('{"items": ["a"]}', "not an object"),
        ('{"items": [{"description": " "}]}', "no description"),
        ('{"items": [{"description": "x", "source_segment_ids": "mic-1"}]}', "not a list"),
    ],
)
def test_parse_reply_rejects_malformed_items(reply: str, reason: str) -> None:
    with pytest.raises(InvalidReplyError, match=reason):
        parse_reply(reply)


def test_parse_reply_accepts_missing_optional_fields() -> None:
    assert parse_reply('{"items": [{"description": "Call", "due": 3}]}') == [
        ("Call", None, None, [])
    ]
