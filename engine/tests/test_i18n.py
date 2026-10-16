from __future__ import annotations

import string
from pathlib import Path

import pytest

from vozata.domain import AppLanguage
from vozata.i18n import TomlLocalizer, load_catalog
from vozata.ports import Localizer


def _placeholders(message: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(message) if name}


def test_every_locale_has_the_same_keys_as_english() -> None:
    english = load_catalog(AppLanguage.EN)

    for language in AppLanguage:
        assert load_catalog(language).keys() == english.keys(), language


def test_every_locale_uses_the_same_placeholders_as_english() -> None:
    english = load_catalog(AppLanguage.EN)

    for language in AppLanguage:
        catalog = load_catalog(language)
        for key, message in english.items():
            assert _placeholders(catalog[key]) == _placeholders(message), (language, key)


def test_keys_are_flat_dotted_names() -> None:
    assert "labels.mic" in load_catalog(AppLanguage.EN)


@pytest.mark.parametrize(
    ("language", "expected"),
    [(AppLanguage.EN, "User 3"), (AppLanguage.PT_BR, "Usuário 3"), (AppLanguage.ES, "Usuario 3")],
)
def test_translate_fills_placeholders(language: AppLanguage, expected: str) -> None:
    assert TomlLocalizer(language).t("labels.user", n=3) == expected


def test_localizer_accepts_the_language_code_and_satisfies_the_port() -> None:
    localizer = TomlLocalizer("pt-BR")

    assert localizer.language is AppLanguage.PT_BR
    assert isinstance(localizer, Localizer)


def test_unknown_language_is_rejected() -> None:
    with pytest.raises(ValueError):
        TomlLocalizer("fr")


def _write_locales(directory: Path, english: str, spanish: str) -> Path:
    (directory / "en.toml").write_text(english, encoding="utf-8")
    (directory / "es.toml").write_text(spanish, encoding="utf-8")
    return directory


def test_missing_key_falls_back_to_english(tmp_path: Path) -> None:
    locales = _write_locales(tmp_path, '[a]\nb = "B {x}"\n', "")

    assert TomlLocalizer(AppLanguage.ES, locales_dir=locales).t("a.b", x=1) == "B 1"


def test_strict_localizer_raises_for_a_key_missing_in_its_language(tmp_path: Path) -> None:
    locales = _write_locales(tmp_path, '[a]\nb = "B"\n', "")

    with pytest.raises(KeyError):
        TomlLocalizer(AppLanguage.ES, locales_dir=locales, strict=True).t("a.b")


def test_key_missing_everywhere_raises(tmp_path: Path) -> None:
    locales = _write_locales(tmp_path, "", "")

    with pytest.raises(KeyError):
        TomlLocalizer(AppLanguage.ES, locales_dir=locales).t("nope")


def test_missing_placeholder_value_raises() -> None:
    with pytest.raises(KeyError):
        TomlLocalizer(AppLanguage.EN).t("labels.user")


def test_missing_locale_file_is_an_empty_catalog(tmp_path: Path) -> None:
    assert load_catalog(AppLanguage.ES, tmp_path) == {}
