from __future__ import annotations

from pathlib import Path

import pytest

from vozata.domain import AppLanguage
from vozata.minutes.template_repository import (
    DEFAULT_TEMPLATE,
    TemplateError,
    TemplateRepository,
    TemplateSection,
    UnknownTemplateError,
)

VALID = """
order = {order}
[en]
name = "Name"
instructions = "Do it."
[[en.sections]]
heading = "One"
guidance = "first"
["pt-BR"]
name = "Nome"
instructions = "Faça."
[["pt-BR".sections]]
heading = "Um"
guidance = "primeiro"
[es]
name = "Nombre"
instructions = "Hazlo."
[[es.sections]]
heading = "Uno"
guidance = "primero"
"""


def write(folder: Path, name: str, text: str) -> None:
    (folder / f"{name}.toml").write_text(text, encoding="utf-8")


def test_bundled_templates_are_valid_in_every_language_and_ordered() -> None:
    repository = TemplateRepository()

    assert repository.ids() == ["general", "daily", "one_on_one", "client", "retrospective"]
    assert DEFAULT_TEMPLATE in repository
    for template in repository.all():
        assert set(template.texts) == set(AppLanguage)


def test_general_keeps_the_phase_04_sections() -> None:
    general = TemplateRepository().get("general")

    headings = [section.heading for section in general.localized(AppLanguage.EN).sections]
    assert headings == ["Context", "Summary", "Topics", "Decisions", "Action items", "Open issues"]
    pt = general.localized("pt-BR")
    assert pt.name == "Reunião geral"
    assert pt.sections[-1].heading == "Questões em aberto"


def test_a_template_is_loaded_with_its_localized_texts(tmp_path: Path) -> None:
    write(tmp_path, "b", VALID.format(order=2))
    write(tmp_path, "a", VALID.format(order=2))
    write(tmp_path, "first", VALID.format(order=1))

    repository = TemplateRepository(tmp_path)

    assert repository.ids() == ["first", "a", "b"]  # by order, then id
    text = repository.get("a").localized(AppLanguage.ES)
    assert (text.id, text.name, text.instructions) == ("a", "Nombre", "Hazlo.")
    assert text.sections == (TemplateSection("Uno", "primero"),)


def test_unknown_template_raises_with_the_id(tmp_path: Path) -> None:
    with pytest.raises(UnknownTemplateError, match="nope"):
        TemplateRepository(tmp_path).get("nope")
    assert "nope" not in TemplateRepository(tmp_path)


def test_missing_language_is_an_error(tmp_path: Path) -> None:
    text = VALID.format(order=1)
    write(tmp_path, "broken", text[: text.index("[es]")])

    with pytest.raises(TemplateError, match=r"broken.toml \[es\]: missing language block"):
        TemplateRepository(tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('name = "Nome"', 'name = "  "', "'name' must be a non-empty string"),
        ('instructions = "Faça."', "instructions = 3", "'instructions' must be a non-empty"),
        ('heading = "Um"', 'heading = ""', "'heading' must be a non-empty string"),
        ('guidance = "primeiro"', "", "'guidance' must be a non-empty string"),
    ],
)
def test_empty_fields_are_errors(tmp_path: Path, old: str, new: str, message: str) -> None:
    write(tmp_path, "broken", VALID.format(order=1).replace(old, new))

    with pytest.raises(TemplateError, match=message):
        TemplateRepository(tmp_path)


def test_sections_must_be_a_non_empty_list_of_tables(tmp_path: Path) -> None:
    no_sections = VALID.format(order=1).replace(
        '[[es.sections]]\nheading = "Uno"\nguidance = "primero"\n', ""
    )
    write(tmp_path, "empty", no_sections)
    with pytest.raises(TemplateError, match=r"empty.toml \[es\]: 'sections' must be a non-empty"):
        TemplateRepository(tmp_path)

    (tmp_path / "empty.toml").unlink()
    write(tmp_path, "scalar", no_sections.replace('name = "Nombre"', 'name = "N"\nsections = [1]'))
    with pytest.raises(TemplateError, match="every section must be a table"):
        TemplateRepository(tmp_path)


def test_invalid_toml_and_order_are_errors(tmp_path: Path) -> None:
    write(tmp_path, "bad", "order = [")
    with pytest.raises(TemplateError, match="bad.toml: invalid TOML"):
        TemplateRepository(tmp_path)

    write(tmp_path, "bad", VALID.format(order='"1"'))
    with pytest.raises(TemplateError, match="'order' must be an integer"):
        TemplateRepository(tmp_path)
