from __future__ import annotations

import pytest

from tests.fakes import minutes_template
from vozata.domain import AppLanguage, ConversationLanguage
from vozata.i18n import TomlLocalizer
from vozata.minutes.prompts import map_prompt, minutes_prompt, reduce_prompt
from vozata.minutes.template_repository import TemplateRepository

TEMPLATES = TemplateRepository()


def loc(language: AppLanguage) -> TomlLocalizer:
    return TomlLocalizer(language, strict=True)


@pytest.mark.parametrize("language", list(AppLanguage))
@pytest.mark.parametrize("template_id", TEMPLATES.ids())
def test_every_template_renders_every_prompt_in_every_language(
    template_id: str, language: AppLanguage
) -> None:
    template = TEMPLATES.get(template_id).localized(language)
    localizer = loc(language)
    headings = "\n".join(f"## {section.heading}" for section in template.sections)

    _, single = minutes_prompt(localizer, template, "[00:00:01] A: hi", ConversationLanguage.EN)
    _, mapped = map_prompt(localizer, template, "x", 1, 2, ConversationLanguage.EN)
    _, reduced = reduce_prompt(localizer, template, ["n1", "n2"], ConversationLanguage.EN)

    for user in (single, mapped, reduced):
        assert template.instructions in user
        assert "{" not in user  # every placeholder was filled
        for section in template.sections:
            assert f"- {section.heading}: {section.guidance}" in user
    assert headings in single
    assert headings in reduced
    assert "## " not in mapped  # notes are not minutes yet


def test_general_prompt_keeps_the_phase_04_sections_and_both_languages() -> None:
    system, user = minutes_prompt(
        loc(AppLanguage.PT_BR),
        minutes_template("pt-BR"),
        "[00:00:01] Eu: Oi",
        ConversationLanguage.ES,
    )

    assert "nunca invente" in system
    assert "conduzida em espanhol" in user
    assert "ata em português do Brasil" in user
    assert "## Contexto\n## Resumo\n## Tópicos\n## Decisões\n## Itens de ação" in user
    assert "- Itens de ação: cada tarefa com responsável e prazo" in user
    assert user.endswith("Transcrição:\n[00:00:01] Eu: Oi")


def test_templates_change_the_sections_and_instructions() -> None:
    _, daily = minutes_prompt(
        loc(AppLanguage.EN), minutes_template(template_id="daily"), "x", ConversationLanguage.EN
    )
    _, client = minutes_prompt(
        loc(AppLanguage.EN), minutes_template(template_id="client"), "x", ConversationLanguage.EN
    )

    assert "daily stand-up" in daily
    assert "## Updates by person" in daily
    assert "## Client needs" not in daily
    assert "## Client needs\n## Commitments\n## Risks\n## Next steps\n## Deadlines" in client


def test_auto_conversation_language_is_described_not_named() -> None:
    _, user = minutes_prompt(
        loc(AppLanguage.EN), minutes_template(), "x", ConversationLanguage.AUTO
    )

    assert "held in the language spoken in the transcript" in user


def test_map_prompt_numbers_the_part() -> None:
    system, user = map_prompt(
        loc(AppLanguage.EN),
        minutes_template(),
        "[00:10:00] Me: part two",
        2,
        3,
        ConversationLanguage.EN,
    )

    assert system == loc(AppLanguage.EN).t("minutes.system")
    assert "part 2 of 3 of a meeting held in English" in user
    assert "notes in English" in user
    assert user.endswith("Transcript:\n[00:10:00] Me: part two")


def test_reduce_prompt_combines_notes_with_the_minutes_instructions() -> None:
    _, user = reduce_prompt(
        loc(AppLanguage.ES),
        minutes_template("es"),
        ["nota uno", "nota dos"],
        ConversationLanguage.PT,
    )

    assert "reunión realizada en portugués" in user
    assert "## Elementos de acción" in user
    assert user.endswith("Notas:\nnota uno\n\n---\n\nnota dos")
