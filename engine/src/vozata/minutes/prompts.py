"""Localized LLM prompts for minutes (all text comes from the locale files)."""

from __future__ import annotations

from collections.abc import Sequence

from vozata.domain import ConversationLanguage
from vozata.ports import Localizer

SECTIONS = ("context", "summary", "topics", "decisions", "action_items", "open_issues")
_NOTES_SEPARATOR = "\n\n---\n\n"

Prompt = tuple[str, str]  # (system, user)


def section_headings(localizer: Localizer) -> list[str]:
    return [localizer.t(f"minutes.section.{section}") for section in SECTIONS]


def _languages(localizer: Localizer, conversation_language: ConversationLanguage) -> dict[str, str]:
    return {
        "conversation_language": localizer.t(f"languages.{conversation_language.value}"),
        "output_language": localizer.t("minutes.output_language"),
    }


def _instructions(localizer: Localizer, conversation_language: ConversationLanguage) -> str:
    sections = "\n".join(f"## {heading}" for heading in section_headings(localizer))
    return localizer.t(
        "minutes.instructions", sections=sections, **_languages(localizer, conversation_language)
    )


def minutes_prompt(
    localizer: Localizer, transcript: str, conversation_language: ConversationLanguage
) -> Prompt:
    """Minutes straight from a transcript that fits in one request."""
    user = "\n\n".join(
        (
            _instructions(localizer, conversation_language),
            f"{localizer.t('minutes.transcript_label')}\n{transcript}",
        )
    )
    return localizer.t("minutes.system"), user


def map_prompt(
    localizer: Localizer,
    transcript_part: str,
    part: int,
    total: int,
    conversation_language: ConversationLanguage,
) -> Prompt:
    """Notes for one part of a long transcript (map step)."""
    instructions = localizer.t(
        "minutes.map_instructions",
        part=part,
        total=total,
        **_languages(localizer, conversation_language),
    )
    user = f"{instructions}\n\n{localizer.t('minutes.transcript_label')}\n{transcript_part}"
    return localizer.t("minutes.system"), user


def reduce_prompt(
    localizer: Localizer, notes: Sequence[str], conversation_language: ConversationLanguage
) -> Prompt:
    """Minutes from the notes of every part (reduce step)."""
    intro = localizer.t(
        "minutes.reduce_instructions", **_languages(localizer, conversation_language)
    )
    user = "\n\n".join(
        (
            intro,
            _instructions(localizer, conversation_language),
            f"{localizer.t('minutes.notes_label')}\n{_NOTES_SEPARATOR.join(notes)}",
        )
    )
    return localizer.t("minutes.system"), user
