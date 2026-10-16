"""TOML-backed localization (architecture §10)."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vozata.domain import AppLanguage

LOCALES_DIR = Path(__file__).parent / "locales"

_log = logging.getLogger(__name__)


def _flatten(table: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for name, value in table.items():
        key = f"{prefix}{name}"
        if isinstance(value, Mapping):
            flat.update(_flatten(value, f"{key}."))
        else:
            flat[key] = str(value)
    return flat


def load_catalog(language: AppLanguage | str, locales_dir: Path = LOCALES_DIR) -> dict[str, str]:
    """Load `<language>.toml` as flat dotted keys; a missing file is an empty catalog."""
    path = locales_dir / f"{AppLanguage(language).value}.toml"
    if not path.exists():
        return {}
    with path.open("rb") as file:
        return _flatten(tomllib.load(file))


class TomlLocalizer:
    """`Localizer` over `locales/<language>.toml` with `{param}` placeholders.

    A key missing in the selected language falls back to English unless `strict` is set.
    """

    def __init__(
        self,
        language: AppLanguage | str,
        *,
        locales_dir: Path = LOCALES_DIR,
        strict: bool = False,
    ) -> None:
        self.language = AppLanguage(language)
        self._strict = strict
        self._messages = load_catalog(self.language, locales_dir)
        self._fallback = (
            {} if self.language is AppLanguage.EN else load_catalog(AppLanguage.EN, locales_dir)
        )

    def t(self, key: str, **params: object) -> str:
        return self._message(key).format_map(params)

    def _message(self, key: str) -> str:
        if key in self._messages:
            return self._messages[key]
        if not self._strict and key in self._fallback:
            _log.warning("Locale %s has no key %s; using English", self.language, key)
            return self._fallback[key]
        raise KeyError(f"Unknown locale key {key!r} for {self.language}")
