"""Settings as the API shows them: JSON values (secrets masked) and the key schema."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from vozata.config import Settings
from vozata.settings_fields import FIELDS

SECRET_MASK = "********"
_DERIVED_DEFAULTS = {"TRANSCRIPTION_LANGUAGE"}  # the default depends on APP_LANGUAGE


def _plain(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    return value


def settings_schema() -> list[dict[str, object]]:
    """`GET /settings` schema: key, type, default, choices, secret, group, applies, options."""
    defaults = Settings()
    return [
        {
            "key": field.key,
            "type": field.type,
            "default": None
            if field.key in _DERIVED_DEFAULTS
            else _plain(getattr(defaults, field.attribute)),
            "choices": [choice.value for choice in field.choices] if field.choices else None,
            "secret": field.secret,
            "group": field.group,
            "applies": field.applies,
            "options_source": field.options_source,
        }
        for field in FIELDS
    ]


def settings_values(settings: Settings) -> dict[str, object]:
    """Current values as JSON values; secrets are masked."""
    values: dict[str, object] = {}
    for field in FIELDS:
        value = _plain(getattr(settings, field.attribute))
        values[field.key] = SECRET_MASK if field.secret and value not in (None, "") else value
    return values
