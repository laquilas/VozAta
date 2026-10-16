"""Settings: the only module that reads the environment (architecture §9).

Each roadmap phase adds the keys it owns. Invalid values fail fast with a `ConfigError`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values

from vozata.domain import AppLanguage, ConversationLanguage, default_conversation_language
from vozata.i18n import TomlLocalizer
from vozata.ports import Localizer

KEYS = (
    "CHUNK_SECONDS",
    "SAMPLE_RATE",
    "APP_LANGUAGE",
    "TRANSCRIPTION_LANGUAGE",
    "MIC_LABEL",
    "SYSTEM_LABEL",
    "OUTPUT_DIR",
)
SUPPORTED_SAMPLE_RATES = (16000,)  # Whisper requirement


class ConfigError(ValueError):
    """An invalid configuration value; the message is a locale key plus parameters."""

    def __init__(self, key: str, value: str, message_key: str, **params: object) -> None:
        self.key = key
        self.value = value
        self.message_key = message_key
        self.params = params
        super().__init__(key, value, message_key)

    def render(self, localizer: Localizer) -> str:
        return localizer.t(
            f"errors.config.{self.message_key}", key=self.key, value=self.value, **self.params
        )

    def __str__(self) -> str:
        return self.render(TomlLocalizer(AppLanguage.EN))


@dataclass(frozen=True)
class Settings:
    chunk_seconds: float = 5.0
    sample_rate: int = 16000
    app_language: AppLanguage = AppLanguage.EN
    transcription_language: ConversationLanguage = ConversationLanguage.EN
    mic_label: str | None = None
    system_label: str | None = None
    output_dir: Path = Path("recordings")


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    """Build `Settings` from `env` (default: `.env` in the working directory + process env).

    Values in `env` override values in `env_file`; empty values mean "not set".
    """
    raw = _read(env, env_file)
    app_language = _choice(raw, "APP_LANGUAGE", AppLanguage, AppLanguage.EN)
    return Settings(
        chunk_seconds=_number(raw, "CHUNK_SECONDS", 5.0, minimum=1, maximum=60),
        sample_rate=_sample_rate(raw),
        app_language=app_language,
        transcription_language=_choice(
            raw,
            "TRANSCRIPTION_LANGUAGE",
            ConversationLanguage,
            default_conversation_language(app_language),
        ),
        mic_label=raw.get("MIC_LABEL"),
        system_label=raw.get("SYSTEM_LABEL"),
        output_dir=Path(raw.get("OUTPUT_DIR", "recordings")),
    )


def _read(env: Mapping[str, str] | None, env_file: Path | None) -> dict[str, str]:
    if env is None:
        env_file = env_file or Path(".env")
        env = os.environ
    merged: dict[str, str | None] = {}
    if env_file is not None and env_file.exists():
        merged.update(dotenv_values(env_file))
    merged.update({key: env[key] for key in KEYS if key in env})
    cleaned = {key: (merged.get(key) or "").strip() for key in KEYS}
    return {key: value for key, value in cleaned.items() if value}


def _choice[E: StrEnum](raw: Mapping[str, str], key: str, enum: type[E], default: E) -> E:
    if key not in raw:
        return default
    try:
        return enum(raw[key])
    except ValueError:
        allowed = ", ".join(member.value for member in enum)
        raise ConfigError(key, raw[key], "invalid_choice", allowed=allowed) from None


def _number(
    raw: Mapping[str, str], key: str, default: float, *, minimum: float, maximum: float
) -> float:
    if key not in raw:
        return default
    value = _parse_float(key, raw[key])
    if not minimum <= value <= maximum:
        raise ConfigError(key, raw[key], "out_of_range", min=minimum, max=maximum)
    return value


def _sample_rate(raw: Mapping[str, str]) -> int:
    if "SAMPLE_RATE" not in raw:
        return SUPPORTED_SAMPLE_RATES[0]
    value = _parse_float("SAMPLE_RATE", raw["SAMPLE_RATE"])
    if value not in SUPPORTED_SAMPLE_RATES:
        allowed = ", ".join(str(rate) for rate in SUPPORTED_SAMPLE_RATES)
        raise ConfigError("SAMPLE_RATE", raw["SAMPLE_RATE"], "invalid_choice", allowed=allowed)
    return int(value)


def _parse_float(key: str, text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise ConfigError(key, text, "not_a_number") from None
