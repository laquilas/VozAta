from __future__ import annotations

import pytest

from vozata.domain import AppLanguage, ConversationLanguage
from vozata.i18n import TomlLocalizer
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt, section_headings


def loc(language: AppLanguage) -> TomlLocalizer:
    return TomlLocalizer(language, strict=True)


@pytest.mark.parametrize(
    ("language", "headings"),
    [
        (
            AppLanguage.EN,
            ["Context", "Summary", "Topics", "Decisions", "Action items", "Open issues"],
        ),
        (
            AppLanguage.PT_BR,
            ["Contexto", "Resumo", "Tópicos", "Decisões", "Itens de ação", "Questões em aberto"],
        ),
        (
            AppLanguage.ES,
            [
                "Contexto",
                "Resumen",
                "Temas",
                "Decisiones",
                "Elementos de acción",
                "Asuntos pendientes",
            ],
        ),
    ],
)
def test_section_headings_follow_the_app_language(
    language: AppLanguage, headings: list[str]
) -> None:
    assert section_headings(loc(language)) == headings


def test_minutes_prompt_states_both_languages_sections_and_transcript() -> None:
    system, user = minutes_prompt(
        loc(AppLanguage.PT_BR), "[00:00:01] Eu: Oi", ConversationLanguage.ES
    )

    assert "nunca invente" in system
    assert "conduzida em espanhol" in user
    assert "ata em português do Brasil" in user
    assert "## Contexto\n## Resumo\n## Tópicos" in user
    assert user.endswith("Transcrição:\n[00:00:01] Eu: Oi")


def test_auto_conversation_language_is_described_not_named() -> None:
    _, user = minutes_prompt(loc(AppLanguage.EN), "x", ConversationLanguage.AUTO)

    assert "held in the language spoken in the transcript" in user


def test_map_prompt_numbers_the_part() -> None:
    system, user = map_prompt(
        loc(AppLanguage.EN), "[00:10:00] Me: part two", 2, 3, ConversationLanguage.EN
    )

    assert system == loc(AppLanguage.EN).t("minutes.system")
    assert "part 2 of 3 of a meeting held in English" in user
    assert "notes in English" in user
    assert user.endswith("Transcript:\n[00:10:00] Me: part two")


def test_reduce_prompt_combines_notes_with_the_minutes_instructions() -> None:
    _, user = reduce_prompt(loc(AppLanguage.ES), ["nota uno", "nota dos"], ConversationLanguage.PT)

    assert "reunión realizada en portugués" in user
    assert "## Elementos de acción" in user
    assert user.endswith("Notas:\nnota uno\n\n---\n\nnota dos")
