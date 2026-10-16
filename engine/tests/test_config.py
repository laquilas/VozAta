from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from vozata.config import ConfigError, Settings, load_settings
from vozata.domain import AppLanguage, ConversationLanguage


def test_defaults_when_nothing_is_set() -> None:
    assert load_settings(env={}) == Settings(
        chunk_seconds=5.0,
        sample_rate=16000,
        app_language=AppLanguage.EN,
        transcription_language=ConversationLanguage.EN,
        mic_label=None,
        system_label=None,
        output_dir=Path("recordings"),
    )


def test_values_are_parsed_from_the_mapping() -> None:
    settings = load_settings(
        env={
            "CHUNK_SECONDS": " 2.5 ",
            "APP_LANGUAGE": "es",
            "TRANSCRIPTION_LANGUAGE": "auto",
            "MIC_LABEL": "Host",
            "SYSTEM_LABEL": "Guests",
            "OUTPUT_DIR": "D:/meetings",
        }
    )

    assert settings.chunk_seconds == 2.5
    assert settings.app_language is AppLanguage.ES
    assert settings.transcription_language is ConversationLanguage.AUTO
    assert (settings.mic_label, settings.system_label) == ("Host", "Guests")
    assert settings.output_dir == Path("D:/meetings")


@pytest.mark.parametrize(
    ("app_language", "expected"),
    [
        ("en", ConversationLanguage.EN),
        ("pt-BR", ConversationLanguage.PT),
        ("es", ConversationLanguage.ES),
    ],
)
def test_empty_transcription_language_is_derived_from_app_language(
    app_language: str, expected: ConversationLanguage
) -> None:
    env = {"APP_LANGUAGE": app_language, "TRANSCRIPTION_LANGUAGE": ""}

    assert load_settings(env=env).transcription_language is expected


def test_empty_label_overrides_mean_no_override() -> None:
    settings = load_settings(env={"MIC_LABEL": "  ", "SYSTEM_LABEL": ""})

    assert settings.mic_label is None
    assert settings.system_label is None


@pytest.mark.parametrize(
    ("key", "value", "message_key", "fragment"),
    [
        ("CHUNK_SECONDS", "abc", "not_a_number", "expected a number"),
        ("CHUNK_SECONDS", "0.5", "out_of_range", "between 1 and 60"),
        ("CHUNK_SECONDS", "61", "out_of_range", "between 1 and 60"),
        ("SAMPLE_RATE", "44100", "invalid_choice", "Allowed values: 16000"),
        ("SAMPLE_RATE", "fast", "not_a_number", "expected a number"),
        ("APP_LANGUAGE", "fr", "invalid_choice", "Allowed values: en, pt-BR, es"),
        ("TRANSCRIPTION_LANGUAGE", "pt-BR", "invalid_choice", "Allowed values: en, pt, es, auto"),
    ],
)
def test_invalid_value_raises_config_error_naming_key_and_allowed_values(
    key: str, value: str, message_key: str, fragment: str
) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    error = caught.value
    assert (error.key, error.value, error.message_key) == (key, value, message_key)
    assert key in str(error)
    assert fragment in str(error)


def test_boundary_chunk_seconds_are_accepted() -> None:
    assert load_settings(env={"CHUNK_SECONDS": "1"}).chunk_seconds == 1.0
    assert load_settings(env={"CHUNK_SECONDS": "60"}).chunk_seconds == 60.0


def test_config_error_renders_through_any_localizer() -> None:
    error = ConfigError("APP_LANGUAGE", "fr", "invalid_choice", allowed="en, pt-BR, es")

    assert error.render(FakeLocalizer()) == (
        "errors.config.invalid_choice(allowed=en, pt-BR, es,key=APP_LANGUAGE,value=fr)"
    )


def test_env_file_is_loaded_and_the_mapping_overrides_it(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CHUNK_SECONDS=8\nAPP_LANGUAGE=pt-BR\nUNRELATED=1\n", encoding="utf-8")

    settings = load_settings(env={"CHUNK_SECONDS": "3"}, env_file=env_file)

    assert settings.chunk_seconds == 3.0
    assert settings.app_language is AppLanguage.PT_BR


def test_missing_env_file_is_ignored(tmp_path: Path) -> None:
    assert load_settings(env={}, env_file=tmp_path / "absent.env") == load_settings(env={})


def test_process_environment_is_used_when_no_mapping_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHUNK_SECONDS", "7")
    (tmp_path / ".env").write_text("APP_LANGUAGE=es\n", encoding="utf-8")

    settings = load_settings()

    assert settings.chunk_seconds == 7.0
    assert settings.app_language is AppLanguage.ES


def test_explicit_supported_sample_rate_is_accepted() -> None:
    assert load_settings(env={"SAMPLE_RATE": "16000"}).sample_rate == 16000
