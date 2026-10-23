from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.domain import Channel, ConversationLanguage, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.action_items import ActionItemExtractor
from vozata.minutes.generator import MinutesGenerator
from vozata.qa.meeting_so_far import MeetingSoFarAnswerer
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


def _segment(start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        f"mic-{int(start):06d}", Channel.MIC, "mic", start, start + 2, text, ()
    )


def _store(tmp_path: Path, *texts: str) -> tuple[FileSessionRepository, str]:
    store = FileSessionRepository(SessionStore(tmp_path))
    session_id = store.create()
    store.write_meta(session_id, {"id": session_id, "status": "recording"})
    sink = store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    for index, text in enumerate(texts):
        sink.emit(_segment(10 * index, text))
    sink.close()
    return store, session_id


def _answerer(store, llm, max_chars=12000, exclude=None):  # type: ignore[no-untyped-def]
    return MeetingSoFarAnswerer(
        llm, store, SpeakerLabeler(FakeLocalizer()), FakeLocalizer(), max_chars, exclude
    )


def test_a_short_meeting_is_read_whole(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path, "A beta sai na terça.", "VozAta, o que foi decidido?")
    llm = FakeLanguageModel(replies=["Beta na terça."])
    chunks: list[str] = []

    answer = _answerer(store, llm, exclude=lambda s: "VozAta" in s.text).answer(
        "O que foi decidido?", session_id, chunks.append
    )

    assert (answer.text, answer.citations) == ("".join(chunks), ())  # the streamed chunks
    assert chunks == ["Beta", "na", "terça."]
    [(system, user, _)] = llm.prompts
    assert system == "qa.system"
    assert "qa.context_label\n[00:00:00] labels.mic: A beta sai na terça." in user
    assert "VozAta" not in user  # the command itself is left out
    assert user.endswith("qa.question_label\nO que foi decidido?")


def test_a_long_meeting_is_read_part_by_part_into_notes(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path, "a" * 50, "b" * 50, "c" * 50)
    llm = FakeLanguageModel(replies=["nota 1", "nota 2", "nota 3", "Resposta."])

    answer = _answerer(store, llm, max_chars=80).answer("Decisões?", session_id, lambda c: None)

    assert answer.text == "Resposta."
    maps = [user for _, user, _ in llm.prompts[:3]]
    assert all("qa.map_instructions(part=" in user and "Decisões?" in user for user in maps)
    final = llm.prompts[3][1]
    assert "qa.notes_label\nnota 1\n\n---\n\nnota 2\n\n---\n\nnota 3" in final


def test_nothing_said_is_not_found_without_the_model(tmp_path: Path) -> None:
    store, session_id = _store(tmp_path)
    llm = FakeLanguageModel()
    chunks: list[str] = []

    answer = _answerer(store, llm).answer("?", session_id, chunks.append)

    assert (answer.text, chunks, llm.prompts) == ("qa.not_found", ["qa.not_found"], [])


def test_a_question_needs_its_meeting(tmp_path: Path) -> None:
    store, _ = _store(tmp_path, "x")

    with pytest.raises(ValueError):
        _answerer(store, FakeLanguageModel()).answer("?", None, lambda c: None)


def test_minutes_and_action_items_leave_the_commands_out() -> None:
    segments = [_segment(0, "A beta sai na terça."), _segment(5, "VozAta, gere a ata.")]
    labeler = SpeakerLabeler(FakeLocalizer())
    exclude = lambda segment: "VozAta" in segment.text  # noqa: E731
    llm = FakeLanguageModel(replies=["# Ata", '{"items": []}'])

    MinutesGenerator(llm, FakeLocalizer(), 12000, minutes_template(), exclude).generate(
        segments, labeler, ConversationLanguage.PT
    )
    ActionItemExtractor(llm, FakeLocalizer(), 12000, exclude).extract(
        segments, labeler, ConversationLanguage.PT
    )

    assert all("VozAta" not in user and "A beta" in user for _, user, _ in llm.prompts)


def test_only_commands_leave_nothing_to_summarize() -> None:
    segments = [_segment(5, "VozAta, gere a ata.")]
    generator = MinutesGenerator(
        FakeLanguageModel(), FakeLocalizer(), 12000, minutes_template(), lambda s: True
    )

    with pytest.raises(ValueError):
        generator.generate(segments, SpeakerLabeler(FakeLocalizer()), ConversationLanguage.PT)
