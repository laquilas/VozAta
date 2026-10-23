from __future__ import annotations

import pytest

from vozata.commands.matcher import CommandMatcher, words
from vozata.domain import VoiceCommand

MINUTES = VoiceCommand("gere a ata", "minutes")
DECIDED = VoiceCommand("o que foi decidido", "ask", "O que foi decidido até agora?")
NEXT = VoiceCommand("quais são os próximos passos", "ask", "Próximos passos?")
MATCHER = CommandMatcher("VozAta", [MINUTES, DECIDED, NEXT])


def test_words_are_casefolded_without_accents_or_punctuation() -> None:
    assert words("VozAta, Gere a ATA!  Ação…") == ["vozata", "gere", "a", "ata", "acao"]


@pytest.mark.parametrize(
    ("said", "command"),
    [
        ("VozAta, gere a ata.", MINUTES),
        ("Voz Ata gere a ata", MINUTES),  # the wake word split in two
        ("vozata, gera a ata", MINUTES),  # a near miss of the phrase
        ("Bom, VozAta, o que foi decidido?", DECIDED),  # the wake word in the middle
        ("Vozatta, quais são os próximos passos até agora?", NEXT),  # misspelled, extra words
        ("Boz Ata, o que foi decidido", DECIDED),
        ("VozAta, então, gere a ata.", MINUTES),  # a few words before the phrase
    ],
)
def test_a_command_after_the_wake_word_is_found(said: str, command: VoiceCommand) -> None:
    assert MATCHER.find(said) == command
    assert MATCHER.addressed(said)


@pytest.mark.parametrize(
    "said",
    [
        "Gere a ata, por favor.",  # no wake word
        "VozAta, bom dia a todos.",  # no command
        "A ata do vozatario saiu.",
        "",
        "VozAta",  # the wake word alone (the command may come in the next segment)
        "VozAta, um dois três quatro cinco seis sete oito nove gere a ata",  # too far
    ],
)
def test_other_speech_is_no_command(said: str) -> None:
    assert MATCHER.find(said) is None
    assert not MATCHER.addressed(said)


def test_after_the_wake_word_gives_the_rest() -> None:
    assert MATCHER.after_wake("Então, VozAta.") == []
    assert MATCHER.after_wake("VozAta gere") == ["gere"]
    assert MATCHER.after_wake("nada aqui") is None


def test_the_best_matching_phrase_wins() -> None:
    near = VoiceCommand("gere a pauta", "ask", "Pauta?")
    matcher = CommandMatcher("VozAta", [near, MINUTES])

    assert matcher.find("VozAta, gere a ata") == MINUTES


def test_an_empty_wake_word_or_phrase_matches_nothing() -> None:
    assert CommandMatcher("  ", [MINUTES]).find("gere a ata") is None
    assert CommandMatcher("VozAta", [VoiceCommand("!!", "minutes")]).find("VozAta, !!") is None
