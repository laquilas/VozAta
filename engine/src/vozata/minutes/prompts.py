"""Localized LLM prompts for minutes, built from the selected template (phase 20).

The frame (languages, Markdown, "—" for empty sections) comes from the locale files; what kind of
meeting it is and which sections the minutes have come from the template. A glossary (the
session vocabulary, phase 19) adds a "use these spellings" block to every prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from vozata.domain import ConversationLanguage
from vozata.minutes.template_repository import LocalizedTemplate
from vozata.ports import Localizer

_NOTES_SEPARATOR = "\n\n---\n\n"

Prompt = tuple[str, str]  # (system, user)


def _params(
    localizer: Localizer, template: LocalizedTemplate, conversation_language: ConversationLanguage
) -> dict[str, str]:
    return {
        "conversation_language": localizer.t(f"languages.{conversation_language.value}"),
        "output_language": localizer.t("minutes.output_language"),
        "template_instructions": template.instructions,
        "sections": "\n".join(f"## {section.heading}" for section in template.sections),
        "guidance": "\n".join(
            f"- {section.heading}: {section.guidance}" for section in template.sections
        ),
    }


def _glossary(localizer: Localizer, glossary: Sequence[str]) -> list[str]:
    """The glossary block, or nothing without terms."""
    return [localizer.t("minutes.glossary", terms=", ".join(glossary))] if glossary else []


def minutes_prompt(
    localizer: Localizer,
    template: LocalizedTemplate,
    transcript: str,
    conversation_language: ConversationLanguage,
    glossary: Sequence[str] = (),
) -> Prompt:
    """Minutes straight from a transcript that fits in one request."""
    params = _params(localizer, template, conversation_language)
    user = "\n\n".join(
        (
            localizer.t("minutes.instructions", **params),
            *_glossary(localizer, glossary),
            f"{localizer.t('minutes.transcript_label')}\n{transcript}",
        )
    )
    return localizer.t("minutes.system"), user


def map_prompt(
    localizer: Localizer,
    template: LocalizedTemplate,
    transcript_part: str,
    part: int,
    total: int,
    conversation_language: ConversationLanguage,
    glossary: Sequence[str] = (),
) -> Prompt:
    """Notes for one part of a long transcript (map step), aimed at the template's sections."""
    params = _params(localizer, template, conversation_language)
    user = "\n\n".join(
        (
            localizer.t("minutes.map_instructions", part=part, total=total, **params),
            *_glossary(localizer, glossary),
            f"{localizer.t('minutes.transcript_label')}\n{transcript_part}",
        )
    )
    return localizer.t("minutes.system"), user


def reduce_prompt(
    localizer: Localizer,
    template: LocalizedTemplate,
    notes: Sequence[str],
    conversation_language: ConversationLanguage,
    glossary: Sequence[str] = (),
) -> Prompt:
    """Minutes from the notes of every part (reduce step)."""
    params = _params(localizer, template, conversation_language)
    user = "\n\n".join(
        (
            localizer.t("minutes.reduce_instructions", **params),
            localizer.t("minutes.instructions", **params),
            *_glossary(localizer, glossary),
            f"{localizer.t('minutes.notes_label')}\n{_NOTES_SEPARATOR.join(notes)}",
        )
    )
    return localizer.t("minutes.system"), user
