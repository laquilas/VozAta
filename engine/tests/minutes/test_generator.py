from __future__ import annotations

import pytest

from tests.fakes import FakeLanguageModel, minutes_template
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
    return MinutesGenerator(llm, EN, max_chars, minutes_template())


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

    MinutesGenerator(llm, pt, 12000, minutes_template("pt-BR")).generate(
        [seg(0, "oi")], SpeakerLabeler(pt), ConversationLanguage.PT
    )

    assert "## Itens de ação" in llm.prompts[0][1]


class _Recording(FakeLanguageModel):
    """Logs generate/release calls in order; can fail either."""

    def __init__(
        self,
        replies: list[str] | None = None,
        generate_error: Exception | None = None,
        release_error: Exception | None = None,
    ) -> None:
        super().__init__(replies)
        self.calls: list[str] = []
        self._generate_error = generate_error
        self._release_error = release_error

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.calls.append("generate")
        if self._generate_error is not None:
            raise self._generate_error
        return super().generate(system, prompt, json_schema)

    def release(self) -> None:
        self.calls.append("release")
        super().release()
        if self._release_error is not None:
            raise self._release_error


def test_single_pass_releases_the_model_after_the_only_call() -> None:
    llm = _Recording(["minutes"])

    generator(llm).generate([seg(0, "hi")], LABELER, ConversationLanguage.EN)

    assert llm.calls == ["generate", "release"]


def test_map_reduce_releases_the_model_only_after_the_reduce_call() -> None:
    llm = _Recording(["n1", "n2", "minutes"])

    generator(llm, max_chars=20).generate(
        [seg(0, "x" * 50), seg(1, "short")], LABELER, ConversationLanguage.EN
    )

    assert llm.calls == ["generate", "generate", "generate", "release"]


def test_the_model_is_released_when_a_call_fails() -> None:
    llm = _Recording(generate_error=LanguageModelError("timeout"))

    with pytest.raises(LanguageModelError, match="timeout"):
        generator(llm).generate([seg(0, "hi")], LABELER, ConversationLanguage.EN)

    assert llm.calls == ["generate", "release"]


def test_a_failed_release_does_not_lose_the_minutes(caplog: pytest.LogCaptureFixture) -> None:
    llm = _Recording(["minutes"], release_error=LanguageModelError("server gone"))

    minutes = generator(llm).generate([seg(0, "hi")], LABELER, ConversationLanguage.EN)

    assert minutes == "minutes"
    assert "server gone" in caplog.text


def test_a_failed_release_does_not_hide_the_original_error() -> None:
    llm = _Recording(
        generate_error=LanguageModelError("timeout"),
        release_error=LanguageModelError("server gone"),
    )

    with pytest.raises(LanguageModelError, match="timeout"):
        generator(llm).generate([seg(0, "hi")], LABELER, ConversationLanguage.EN)


def test_empty_transcript_does_not_touch_the_model() -> None:
    llm = _Recording()

    with pytest.raises(ValueError):
        generator(llm).generate([], LABELER, ConversationLanguage.EN)

    assert llm.calls == []


def test_the_template_sets_the_sections_of_every_prompt() -> None:
    llm = FakeLanguageModel(["n1", "n2", "minutes"])
    daily = MinutesGenerator(llm, EN, 20, minutes_template(template_id="daily"))

    daily.generate([seg(0, "first line"), seg(9, "second line")], LABELER, ConversationLanguage.EN)

    assert daily.template_id == "daily"
    users = [user for _, user, _ in llm.prompts]
    assert all("- Blockers:" in user for user in users)
    assert "## Updates by person" in users[-1]
