from __future__ import annotations

import pytest

from vozata.domain import AppLanguage
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler


def _labeler(language: AppLanguage, **kwargs: object) -> SpeakerLabeler:
    return SpeakerLabeler(TomlLocalizer(language, strict=True), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("language", "mic", "system", "user"),
    [
        (AppLanguage.EN, "Me", "Others", "User 2"),
        (AppLanguage.PT_BR, "Eu", "Outros", "Usuário 2"),
        (AppLanguage.ES, "Yo", "Otros", "Usuario 2"),
    ],
)
def test_default_labels_follow_the_app_language(
    language: AppLanguage, mic: str, system: str, user: str
) -> None:
    labeler = _labeler(language)

    assert labeler.label("mic") == mic
    assert labeler.label("system") == system
    assert labeler.label("system:2") == user


def test_overrides_win_over_localized_defaults() -> None:
    labeler = _labeler(AppLanguage.EN, mic_override="Host", system_override="Guests")

    assert labeler.label("mic") == "Host"
    assert labeler.label("system") == "Guests"
    assert labeler.label("system:1") == "User 1"


def test_names_win_over_overrides_and_defaults() -> None:
    labeler = _labeler(
        AppLanguage.PT_BR,
        mic_override="Host",
        names={"mic": "Lucas", "system:3": "Ana"},
    )

    assert labeler.label("mic") == "Lucas"
    assert labeler.label("system:3") == "Ana"
    assert labeler.label("system:4") == "Usuário 4"


def test_blank_names_are_ignored() -> None:
    labeler = _labeler(AppLanguage.EN, names={"system:1": "  "})

    assert labeler.label("system:1") == "User 1"


def test_with_names_keeps_the_overrides_and_adds_session_names() -> None:
    labeler = _labeler(AppLanguage.ES, system_override="Guests")

    session = labeler.with_names({"system:2": "Ana"})

    assert labeler.with_names({}) is labeler
    assert session.label("system:2") == "Ana"
    assert session.label("system:1") == "Usuario 1"
    assert session.label("system") == "Guests"
    assert labeler.label("system:2") == "Usuario 2"


@pytest.mark.parametrize("speaker_id", ["speaker", "system:", "system:x", "system:0", "mic:1"])
def test_unknown_speaker_ids_are_rejected(speaker_id: str) -> None:
    with pytest.raises(ValueError):
        _labeler(AppLanguage.EN).label(speaker_id)
