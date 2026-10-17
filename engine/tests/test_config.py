from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from vozata.config import ConfigError, Settings, load_settings
from vozata.domain import AppLanguage, ChunkMode, ConversationLanguage, MixMode, WhisperDevice


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


def test_mix_mode_defaults_to_mono_and_accepts_stereo() -> None:
    assert load_settings(env={}).mix_mode is MixMode.MONO
    assert load_settings(env={"MIX_MODE": "stereo"}).mix_mode is MixMode.STEREO


def test_invalid_mix_mode_names_the_allowed_values() -> None:
    with pytest.raises(ConfigError, match="Allowed values: mono, stereo"):
        load_settings(env={"MIX_MODE": "surround"})


def test_transcription_defaults() -> None:
    settings = load_settings(env={})

    assert settings.tail_margin_seconds == 0.6
    assert settings.pause_gap_seconds == 0.5
    assert settings.max_carry_seconds == 15.0
    assert settings.silence_rms_threshold == 0.01
    assert settings.stt_provider == "faster_whisper"
    assert settings.whisper_model == "large-v3-turbo"
    assert settings.whisper_device is WhisperDevice.AUTO
    assert settings.whisper_compute_type == "int8_float16"
    assert settings.whisper_cpu_model == "small"


def test_transcription_values_are_parsed() -> None:
    settings = load_settings(
        env={
            "TAIL_MARGIN_SECONDS": "0.4",
            "PAUSE_GAP_SECONDS": "0.8",
            "MAX_CARRY_SECONDS": "20",
            "SILENCE_RMS_THRESHOLD": "0.02",
            "STT_PROVIDER": "openai_compatible",
            "WHISPER_MODEL": "medium",
            "WHISPER_DEVICE": "cpu",
            "WHISPER_COMPUTE_TYPE": "float16",
            "WHISPER_CPU_MODEL": "base",
        }
    )

    assert (settings.tail_margin_seconds, settings.pause_gap_seconds) == (0.4, 0.8)
    assert (settings.max_carry_seconds, settings.silence_rms_threshold) == (20.0, 0.02)
    assert settings.stt_provider == "openai_compatible"
    assert (settings.whisper_model, settings.whisper_cpu_model) == ("medium", "base")
    assert settings.whisper_device is WhisperDevice.CPU
    assert settings.whisper_compute_type == "float16"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TAIL_MARGIN_SECONDS", "-0.1"),
        ("TAIL_MARGIN_SECONDS", "6"),
        ("PAUSE_GAP_SECONDS", "0"),
        ("MAX_CARRY_SECONDS", "0.5"),
        ("MAX_CARRY_SECONDS", "121"),
        ("SILENCE_RMS_THRESHOLD", "1.5"),
        ("WHISPER_DEVICE", "tpu"),
    ],
)
def test_invalid_transcription_values_raise(key: str, value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    assert caught.value.key == key


def test_minutes_defaults() -> None:
    settings = load_settings(env={})

    assert settings.llm_provider == "ollama"
    assert settings.ollama_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen2.5:7b"
    assert settings.llm_max_chars == 12000
    assert settings.ollama_keep_alive == "0"


def test_minutes_values_are_parsed() -> None:
    settings = load_settings(
        env={
            "LLM_PROVIDER": "custom",
            "OLLAMA_URL": "https://ollama.lan:8443/",
            "OLLAMA_MODEL": "qwen2.5:3b",
            "LLM_MAX_CHARS": "20000",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
    )

    assert settings.llm_provider == "custom"
    assert settings.ollama_url == "https://ollama.lan:8443"  # trailing slash dropped
    assert settings.ollama_model == "qwen2.5:3b"
    assert settings.llm_max_chars == 20000
    assert settings.ollama_keep_alive == "5m"


@pytest.mark.parametrize("value", ["0", "-1", "300", "5m", "1h30m", "1.5h", "250ms", "-1m"])
def test_ollama_keep_alive_accepts_seconds_and_durations(value: str) -> None:
    assert load_settings(env={"OLLAMA_KEEP_ALIVE": value}).ollama_keep_alive == value


@pytest.mark.parametrize(
    ("key", "value", "message_key"),
    [
        ("OLLAMA_URL", "localhost:11434", "invalid_url"),
        ("OLLAMA_URL", "ftp://host", "invalid_url"),
        ("LLM_MAX_CHARS", "999", "out_of_range"),
        ("LLM_MAX_CHARS", "many", "not_a_number"),
        ("OLLAMA_KEEP_ALIVE", "forever", "invalid_duration"),
        ("OLLAMA_KEEP_ALIVE", "5 m", "invalid_duration"),
        ("OLLAMA_KEEP_ALIVE", "m", "invalid_duration"),
        ("OLLAMA_KEEP_ALIVE", "5d", "invalid_duration"),
    ],
)
def test_invalid_minutes_values_raise(key: str, value: str, message_key: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    assert (caught.value.key, caught.value.message_key) == (key, message_key)
    assert key in str(caught.value)


def test_generate_minutes_defaults_to_true() -> None:
    assert load_settings(env={}).generate_minutes is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False), ("0", False)],
)
def test_generate_minutes_accepts_boolean_words(value: str, expected: bool) -> None:
    assert load_settings(env={"GENERATE_MINUTES": value}).generate_minutes is expected


def test_invalid_generate_minutes_names_the_allowed_values() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings(env={"GENERATE_MINUTES": "maybe"})

    assert error.value.key == "GENERATE_MINUTES"
    assert error.value.message_key == "invalid_choice"
    assert error.value.params == {"allowed": "true, false"}


def test_api_defaults_and_values() -> None:
    assert (load_settings(env={}).api_host, load_settings(env={}).api_port) == ("127.0.0.1", 8765)

    settings = load_settings(env={"API_HOST": "localhost", "API_PORT": "9000"})

    assert (settings.api_host, settings.api_port) == ("localhost", 9000)


@pytest.mark.parametrize("value", ["0", "70000", "80.5"])
def test_invalid_api_port_raises(value: str) -> None:
    with pytest.raises(ConfigError) as error:
        load_settings(env={"API_PORT": value})

    assert error.value.key == "API_PORT"


def test_every_key_has_exactly_one_field_description() -> None:
    from vozata.config import KEYS
    from vozata.settings_fields import FIELDS

    assert tuple(field.key for field in FIELDS) == KEYS
    assert len(set(KEYS)) == len(KEYS)
    assert {"API_HOST", "API_PORT", "GENERATE_MINUTES", "MIX_MODE"} <= set(KEYS)


def test_settings_schema_describes_type_default_and_choices() -> None:
    from vozata.settings_view import settings_schema

    schema = {item["key"]: item for item in settings_schema()}

    assert schema["CHUNK_SECONDS"] == {
        "key": "CHUNK_SECONDS",
        "type": "number",
        "default": 5.0,
        "choices": None,
        "secret": False,
        "group": "segmentation",
        "applies": "next_session",
    }
    assert schema["MIX_MODE"]["choices"] == ["mono", "stereo"]
    assert schema["MIX_MODE"]["type"] == "choice"
    assert schema["GENERATE_MINUTES"]["type"] == "bool"
    assert schema["API_PORT"] == {
        "key": "API_PORT",
        "type": "integer",
        "default": 8765,
        "choices": None,
        "secret": False,
        "group": "api",
        "applies": "restart",
    }
    assert schema["TRANSCRIPTION_LANGUAGE"]["default"] is None
    assert schema["TRANSCRIPTION_LANGUAGE"]["choices"] == ["en", "pt", "es", "auto"]


def test_settings_values_are_plain_json_values() -> None:
    from vozata.settings_view import settings_values

    values = settings_values(load_settings(env={"MIX_MODE": "stereo", "MIC_LABEL": "Host"}))

    assert values["MIX_MODE"] == "stereo"
    assert values["MIC_LABEL"] == "Host"
    assert values["SYSTEM_LABEL"] is None
    assert values["OUTPUT_DIR"] == "recordings"
    assert values["CHUNK_SECONDS"] == 5.0
    assert values["GENERATE_MINUTES"] is True
    assert values["APP_LANGUAGE"] == "en"


def test_secret_values_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    from vozata import settings_view

    secret = dataclasses.replace(settings_view.FIELDS[0], secret=True)
    monkeypatch.setattr(settings_view, "FIELDS", (secret, *settings_view.FIELDS[1:]))

    values = settings_view.settings_values(load_settings(env={}))

    assert values[secret.key] == "********"


def test_segmentation_defaults() -> None:
    settings = load_settings(env={})

    assert settings.chunk_mode is ChunkMode.VAD
    assert settings.vad_threshold == 0.5
    assert settings.vad_min_silence_ms == 600
    assert settings.vad_min_chunk_seconds == 1.0
    assert settings.vad_max_chunk_seconds == 15.0
    assert settings.vad_speech_pad_ms == 200


def test_segmentation_values_are_parsed() -> None:
    settings = load_settings(
        env={
            "CHUNK_MODE": "fixed",
            "VAD_THRESHOLD": "0.6",
            "VAD_MIN_SILENCE_MS": "800",
            "VAD_MIN_CHUNK_SECONDS": "0.5",
            "VAD_MAX_CHUNK_SECONDS": "20",
            "VAD_SPEECH_PAD_MS": "100",
        }
    )

    assert settings.chunk_mode is ChunkMode.FIXED
    assert (settings.vad_threshold, settings.vad_min_silence_ms) == (0.6, 800)
    assert (settings.vad_min_chunk_seconds, settings.vad_max_chunk_seconds) == (0.5, 20.0)
    assert settings.vad_speech_pad_ms == 100


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("CHUNK_MODE", "auto"),
        ("VAD_THRESHOLD", "0"),
        ("VAD_THRESHOLD", "1"),
        ("VAD_MIN_SILENCE_MS", "50"),
        ("VAD_MIN_SILENCE_MS", "5001"),
        ("VAD_MIN_SILENCE_MS", "600.5"),
        ("VAD_MIN_CHUNK_SECONDS", "-1"),
        ("VAD_MIN_CHUNK_SECONDS", "6"),
        ("VAD_MAX_CHUNK_SECONDS", "4"),
        ("VAD_MAX_CHUNK_SECONDS", "61"),
        ("VAD_SPEECH_PAD_MS", "-1"),
        ("VAD_SPEECH_PAD_MS", "1001"),
    ],
)
def test_invalid_segmentation_values_raise(key: str, value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    assert caught.value.key == key


def test_whisper_keep_loaded_defaults_to_false_and_accepts_booleans() -> None:
    assert load_settings(env={}).whisper_keep_loaded is False
    assert load_settings(env={"WHISPER_KEEP_LOADED": "true"}).whisper_keep_loaded is True
    with pytest.raises(ConfigError) as caught:
        load_settings(env={"WHISPER_KEEP_LOADED": "sometimes"})
    assert caught.value.key == "WHISPER_KEEP_LOADED"


def test_live_partials_defaults_and_values() -> None:
    settings = load_settings(env={})
    assert (settings.live_partials, settings.partial_interval_seconds) == (True, 1.5)

    settings = load_settings(env={"LIVE_PARTIALS": "false", "PARTIAL_INTERVAL_SECONDS": "3"})
    assert (settings.live_partials, settings.partial_interval_seconds) == (False, 3.0)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LIVE_PARTIALS", "maybe"),
        ("PARTIAL_INTERVAL_SECONDS", "0.4"),
        ("PARTIAL_INTERVAL_SECONDS", "11"),
    ],
)
def test_invalid_live_partial_values_raise(key: str, value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    assert caught.value.key == key


def test_every_key_belongs_to_a_known_group_and_restart_keys_are_explicit() -> None:
    from vozata.settings_fields import FIELDS, GROUPS

    assert {field.group for field in FIELDS} == set(GROUPS)
    assert {field.applies for field in FIELDS} == {"next_session", "restart"}
    restart = {field.key for field in FIELDS if field.applies == "restart"}
    assert restart == {
        "API_HOST",
        "API_PORT",
        "STT_PROVIDER",
        "WHISPER_MODEL",
        "WHISPER_DEVICE",
        "WHISPER_COMPUTE_TYPE",
        "WHISPER_CPU_MODEL",
        "WHISPER_KEEP_LOADED",
        "OUTPUT_DIR",
        "SAMPLE_RATE",
    }


def test_external_stt_defaults_values_and_secret_mask() -> None:
    from vozata.settings_view import settings_values

    defaults = load_settings(env={})
    assert (defaults.openai_stt_url, defaults.openai_stt_key, defaults.openai_stt_model) == (
        "https://api.openai.com/v1",
        None,
        "whisper-1",
    )
    assert settings_values(defaults)["OPENAI_STT_KEY"] is None  # nothing to mask

    settings = load_settings(
        env={
            "OPENAI_STT_URL": "https://api.groq.com/openai/v1/",
            "OPENAI_STT_KEY": "gsk_secret",
            "OPENAI_STT_MODEL": "whisper-large-v3",
        }
    )
    assert settings.openai_stt_url == "https://api.groq.com/openai/v1"
    assert (settings.openai_stt_key, settings.openai_stt_model) == (
        "gsk_secret",
        "whisper-large-v3",
    )
    assert settings_values(settings)["OPENAI_STT_KEY"] == "********"


def test_an_invalid_external_stt_url_is_rejected() -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={"OPENAI_STT_URL": "api.openai.com"})

    assert (caught.value.key, caught.value.message_key) == ("OPENAI_STT_URL", "invalid_url")


def test_echo_dedupe_defaults_and_values() -> None:
    settings = load_settings(env={})
    assert (
        settings.echo_dedupe_enabled,
        settings.echo_similarity,
        settings.echo_hold_seconds,
    ) == (True, 0.85, None)

    settings = load_settings(
        env={"ECHO_DEDUPE_ENABLED": "false", "ECHO_SIMILARITY": "0.7", "ECHO_HOLD_SECONDS": "12"}
    )
    assert (
        settings.echo_dedupe_enabled,
        settings.echo_similarity,
        settings.echo_hold_seconds,
    ) == (False, 0.7, 12.0)


def test_echo_hold_defaults_to_chunk_seconds_plus_three() -> None:
    assert load_settings(env={}).effective_echo_hold_seconds == 8.0
    assert load_settings(env={"CHUNK_SECONDS": "10"}).effective_echo_hold_seconds == 13.0
    assert load_settings(env={"ECHO_HOLD_SECONDS": "4"}).effective_echo_hold_seconds == 4.0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ECHO_DEDUPE_ENABLED", "maybe"),
        ("ECHO_SIMILARITY", "0.4"),
        ("ECHO_SIMILARITY", "1.1"),
        ("ECHO_HOLD_SECONDS", "0.5"),
        ("ECHO_HOLD_SECONDS", "61"),
    ],
)
def test_invalid_echo_dedupe_values_raise(key: str, value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={key: value})

    assert caught.value.key == key


def test_diarization_defaults_values_and_secret_mask() -> None:
    from vozata.settings_view import settings_values

    defaults = load_settings(env={})
    assert defaults.diarization_enabled is False
    assert defaults.diarization_provider == "pyannote"
    assert defaults.diarization_device is WhisperDevice.AUTO
    assert (defaults.hf_token, defaults.min_speakers, defaults.max_speakers) == (None, None, None)
    assert settings_values(defaults)["HF_TOKEN"] is None

    settings = load_settings(
        env={
            "DIARIZATION_ENABLED": "true",
            "DIARIZATION_DEVICE": "cpu",
            "HF_TOKEN": "hf_secret",
            "MIN_SPEAKERS": "2",
            "MAX_SPEAKERS": "3",
        }
    )
    assert settings.diarization_enabled is True
    assert settings.diarization_device is WhisperDevice.CPU
    assert (settings.hf_token, settings.min_speakers, settings.max_speakers) == ("hf_secret", 2, 3)
    assert settings_values(settings)["HF_TOKEN"] == "********"


@pytest.mark.parametrize(
    ("env", "key"),
    [
        ({"MIN_SPEAKERS": "0"}, "MIN_SPEAKERS"),
        ({"MAX_SPEAKERS": "21"}, "MAX_SPEAKERS"),
        ({"MAX_SPEAKERS": "2.5"}, "MAX_SPEAKERS"),
        ({"MIN_SPEAKERS": "4", "MAX_SPEAKERS": "3"}, "MIN_SPEAKERS"),
        ({"DIARIZATION_DEVICE": "tpu"}, "DIARIZATION_DEVICE"),
    ],
)
def test_invalid_diarization_values_are_rejected(env: dict[str, str], key: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env=env)

    assert caught.value.key == key


def test_one_speaker_bound_alone_is_accepted() -> None:
    settings = load_settings(env={"MAX_SPEAKERS": "4"})

    assert (settings.min_speakers, settings.max_speakers) == (None, 4)


def test_minutes_template_defaults_to_general_and_accepts_bundled_ids() -> None:
    assert load_settings(env={}).minutes_template == "general"
    assert load_settings(env={"MINUTES_TEMPLATE": "daily"}).minutes_template == "daily"


def test_unknown_minutes_template_names_the_bundled_ids() -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={"MINUTES_TEMPLATE": "weekly"})

    assert (caught.value.key, caught.value.message_key) == ("MINUTES_TEMPLATE", "invalid_choice")
    assert caught.value.params == {"allowed": "general, daily, one_on_one, client, retrospective"}
