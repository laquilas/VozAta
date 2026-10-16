from __future__ import annotations

import pytest

from tests.fakes import FakeLanguageModel
from vozata.domain import AppLanguage, Channel, ConversationLanguage, TranscriptSegment
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError

EN = TomlLocalizer(AppLanguage.EN, strict=True)
LABELER = SpeakerLabeler(EN)


def seg(start: float, text: str, speaker: str = "mic") -> TranscriptSegment:
    channel = Channel.MIC if speaker == "mic" else Channel.SYSTEM
    return TranscriptSegment(f"{speaker}-{start:g}", channel, speaker, start, start + 1, text, ())


def generator(llm: FakeLanguageModel, max_chars: int = 12000) -> MinutesGenerator:
    return MinutesGenerator(llm, EN, max_chars)


def test_short_transcript_takes_a_single_pass() -> None:
    llm = FakeLanguageModel(["  ## Context\n...  "])

    minutes = generator(llm).generate(
        [seg(5, "Second", "system"), seg(1, "First")], LABELER, ConversationLanguage.EN
    )

    assert minutes == "## Context\n..."
    assert len(llm.prompts) == 1
    _, user, schema = llm.prompts[0]
    assert user.endswith("Transcript:\n[00:00:01] Me: First\n[00:00:05] Others: Second")
    assert schema is None


def test_long_transcript_is_mapped_per_part_then_reduced() -> None:
    segments = [seg(i * 10, f"sentence number {i}") for i in range(6)]
    line_length = len("[00:00:00] Me: sentence number 0")
    llm = FakeLanguageModel(["notes A", "notes B", "notes C", "final minutes"])

    minutes = generator(llm, max_chars=2 * line_length + 1).generate(
        segments, LABELER, ConversationLanguage.PT
    )

    assert minutes == "final minutes"
    users = [user for _, user, _ in llm.prompts]
    assert len(users) == 4  # 3 map calls + 1 reduce
    assert "part 1 of 3" in users[0]
    assert users[0].endswith("[00:00:00] Me: sentence number 0\n[00:00:10] Me: sentence number 1")
    assert "part 3 of 3" in users[2]
    assert "held in Portuguese" in users[3]
    assert users[3].endswith("Notes:\nnotes A\n\n---\n\nnotes B\n\n---\n\nnotes C")


def test_a_line_longer_than_the_limit_is_a_part_of_its_own() -> None:
    llm = FakeLanguageModel(["n1", "n2", "minutes"])

    generator(llm, max_chars=20).generate(
        [seg(0, "x" * 50), seg(1, "short")], LABELER, ConversationLanguage.EN
    )

    assert ["part 1 of 2" in u for _, u, _ in llm.prompts[:2]] == [True, False]
    assert len(llm.prompts) == 3


def test_empty_transcript_is_rejected_without_calling_the_model() -> None:
    llm = FakeLanguageModel()

    with pytest.raises(ValueError):
        generator(llm).generate([], LABELER, ConversationLanguage.EN)

    assert llm.prompts == []


def test_language_model_errors_propagate() -> None:
    class Unreachable(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            raise LanguageModelError("connection refused")

    with pytest.raises(LanguageModelError):
        generator(Unreachable()).generate([seg(0, "hi")], LABELER, ConversationLanguage.EN)


def test_headings_follow_the_app_language() -> None:
    llm = FakeLanguageModel(["ata"])
    pt = TomlLocalizer(AppLanguage.PT_BR, strict=True)

    MinutesGenerator(llm, pt, 12000).generate(
        [seg(0, "oi")], SpeakerLabeler(pt), ConversationLanguage.PT
    )

    assert "## Itens de ação" in llm.prompts[0][1]
