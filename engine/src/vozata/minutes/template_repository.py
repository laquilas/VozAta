"""Minutes templates: `minutes/templates/<id>.toml`, one block per app language (phase 20).

```toml
order = 1                      # position in `GET /templates`
[en]
name = "General meeting"
instructions = "..."           # what kind of meeting this is and what matters in its minutes
[[en.sections]]                # level-2 headings of the minutes, in order
heading = "Context"
guidance = "..."               # what goes under the heading
```
"""

from __future__ import annotations

import functools
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vozata.domain import AppLanguage

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE = "general"


class TemplateError(ValueError):
    """A template file is malformed (missing language, empty field, no sections)."""


class UnknownTemplateError(LookupError):
    """No template has this id; `str()` is the id."""


@dataclass(frozen=True)
class TemplateSection:
    heading: str
    guidance: str


@dataclass(frozen=True)
class LocalizedTemplate:
    """One template in one language: what the minutes prompt is built from."""

    id: str
    name: str
    instructions: str
    sections: tuple[TemplateSection, ...]


@dataclass(frozen=True)
class MinutesTemplate:
    id: str
    order: int
    texts: Mapping[AppLanguage, LocalizedTemplate]

    def localized(self, language: AppLanguage | str) -> LocalizedTemplate:
        return self.texts[AppLanguage(language)]


class TemplateRepository:
    """Loads and validates every `*.toml` template of a folder once, at construction."""

    def __init__(self, directory: Path = TEMPLATES_DIR) -> None:
        loaded = [_load(path) for path in sorted(directory.glob("*.toml"))]
        self._templates = {
            template.id: template for template in sorted(loaded, key=lambda t: (t.order, t.id))
        }

    def ids(self) -> list[str]:
        return list(self._templates)

    def all(self) -> list[MinutesTemplate]:
        return list(self._templates.values())

    def __contains__(self, template_id: object) -> bool:
        return template_id in self._templates

    def get(self, template_id: str) -> MinutesTemplate:
        try:
            return self._templates[template_id]
        except KeyError:
            raise UnknownTemplateError(template_id) from None


@functools.cache
def bundled_templates() -> TemplateRepository:
    """The templates shipped with the package (package data), loaded once."""
    return TemplateRepository()


def _load(path: Path) -> MinutesTemplate:
    template_id = path.stem
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise TemplateError(f"{path.name}: invalid TOML ({error})") from None
    order = data.get("order", 0)
    if not isinstance(order, int):
        raise TemplateError(f"{path.name}: 'order' must be an integer")
    texts = {
        language: _localized(path.name, template_id, language, data.get(language.value))
        for language in AppLanguage
    }
    return MinutesTemplate(template_id, order, texts)


def _localized(file: str, template_id: str, language: AppLanguage, block: Any) -> LocalizedTemplate:
    where = f"{file} [{language.value}]"
    if not isinstance(block, Mapping):
        raise TemplateError(f"{where}: missing language block")
    sections = block.get("sections")
    if not isinstance(sections, list) or not sections:
        raise TemplateError(f"{where}: 'sections' must be a non-empty list")
    return LocalizedTemplate(
        id=template_id,
        name=_text(block, "name", where),
        instructions=_text(block, "instructions", where),
        sections=tuple(
            TemplateSection(_text(item, "heading", where), _text(item, "guidance", where))
            for item in (_table(item, where) for item in sections)
        ),
    )


def _table(item: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise TemplateError(f"{where}: every section must be a table")
    return item


def _text(block: Mapping[str, Any], key: str, where: str) -> str:
    value = block.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TemplateError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()
