"""Settings: the only module that reads the environment (architecture §9).

Each roadmap phase adds the keys it owns. Invalid values fail fast with a `ConfigError`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values

from vozata.domain import (
    AppLanguage,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    WhisperDevice,
    default_conversation_language,
)
from vozata.i18n import TomlLocalizer
from vozata.minutes.template_repository import DEFAULT_TEMPLATE, bundled_templates
from vozata.ports import Localizer
from vozata.settings_fields import FIELDS

KEYS = tuple(field.key for field in FIELDS)

_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")
SUPPORTED_SAMPLE_RATES = (16000,)  # Whisper requirement
MAX_SPEAKERS_LIMIT = 20
# Ollama `keep_alive`: whole seconds (`0`, `-1`, `300`) or a Go duration (`5m`, `1h30m`, `250ms`).
_DURATION = re.compile(r"-?\d+|-?(\d+(\.\d+)?(ns|us|µs|ms|s|m|h))+")


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
    mix_mode: MixMode = MixMode.MONO
    # Transcription (phase 03)
    tail_margin_seconds: float = 0.6
    pause_gap_seconds: float = 0.5
    max_carry_seconds: float = 15.0
    silence_rms_threshold: float = 0.01
    stt_provider: str = "faster_whisper"
    whisper_model: str = "large-v3-turbo"
    whisper_device: WhisperDevice = WhisperDevice.AUTO
    whisper_compute_type: str = "int8_float16"
    whisper_cpu_model: str = "small"
    whisper_keep_loaded: bool = False  # serve: keep the transcriber between sessions (phase 26)
    # External STT API (phase 12)
    openai_stt_url: str = "https://api.openai.com/v1"
    openai_stt_key: str | None = None
    openai_stt_model: str = "whisper-1"
    # Speaker identification (phase 14); the device uses the same auto / cuda / cpu choices
    diarization_enabled: bool = False
    diarization_provider: str = "pyannote"
    diarization_device: WhisperDevice = WhisperDevice.AUTO
    hf_token: str | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    # Pause-based segmentation (phase 27)
    chunk_mode: ChunkMode = ChunkMode.VAD
    vad_threshold: float = 0.5
    vad_min_silence_ms: int = 600
    vad_min_chunk_seconds: float = 1.0
    vad_max_chunk_seconds: float = 15.0
    vad_speech_pad_ms: int = 200
    # Live interim text (phase 28)
    live_partials: bool = True
    partial_interval_seconds: float = 1.5
    # Echo dedupe (phase 18)
    echo_dedupe_enabled: bool = True
    echo_similarity: float = 0.85
    echo_hold_seconds: float | None = None  # None: CHUNK_SECONDS + 3
    # Custom vocabulary (phase 19)
    vocabulary_file: Path | None = None  # None: `vocabulary.txt` next to `.env`
    context_prompt_chars: int = 200  # rolling context prompt length, 0 = off
    # Editable transcript (phase 21)
    low_confidence_threshold: float = 0.5
    # Minutes (phase 04)
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_max_chars: int = 12000
    # Minutes templates (phase 20)
    minutes_template: str = DEFAULT_TEMPLATE
    # LLM VRAM release (phase 25)
    ollama_keep_alive: str = "0"
    # Session (phase 05)
    generate_minutes: bool = True
    # Crash recovery (phase 17)
    autosave_seconds: float = 10.0  # `session.json` heartbeat interval
    # API (phase 06)
    api_host: str = "127.0.0.1"
    api_port: int = 8765

    @property
    def effective_echo_hold_seconds(self) -> float:
        """How long mic segments wait for a matching system segment (phase 18)."""
        if self.echo_hold_seconds is not None:
            return self.echo_hold_seconds
        return self.chunk_seconds + 3


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    """Build `Settings` from `env` (default: `.env` in the working directory + process env).

    Values in `env` override values in `env_file`; empty values mean "not set".
    """
    raw = _read(env, env_file)
    app_language = _choice(raw, "APP_LANGUAGE", AppLanguage, AppLanguage.EN)
    min_speakers, max_speakers = _speaker_bounds(raw)
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
        mix_mode=_choice(raw, "MIX_MODE", MixMode, MixMode.MONO),
        tail_margin_seconds=_number(raw, "TAIL_MARGIN_SECONDS", 0.6, minimum=0, maximum=5),
        pause_gap_seconds=_number(raw, "PAUSE_GAP_SECONDS", 0.5, minimum=0.05, maximum=5),
        max_carry_seconds=_number(raw, "MAX_CARRY_SECONDS", 15.0, minimum=1, maximum=120),
        silence_rms_threshold=_number(raw, "SILENCE_RMS_THRESHOLD", 0.01, minimum=0, maximum=1),
        stt_provider=raw.get("STT_PROVIDER", "faster_whisper"),
        whisper_model=raw.get("WHISPER_MODEL", "large-v3-turbo"),
        whisper_device=_choice(raw, "WHISPER_DEVICE", WhisperDevice, WhisperDevice.AUTO),
        whisper_compute_type=raw.get("WHISPER_COMPUTE_TYPE", "int8_float16"),
        whisper_cpu_model=raw.get("WHISPER_CPU_MODEL", "small"),
        whisper_keep_loaded=_flag(raw, "WHISPER_KEEP_LOADED", False),
        openai_stt_url=_url(raw, "OPENAI_STT_URL", "https://api.openai.com/v1"),
        openai_stt_key=raw.get("OPENAI_STT_KEY"),
        openai_stt_model=raw.get("OPENAI_STT_MODEL", "whisper-1"),
        diarization_enabled=_flag(raw, "DIARIZATION_ENABLED", False),
        diarization_provider=raw.get("DIARIZATION_PROVIDER", "pyannote"),
        diarization_device=_choice(raw, "DIARIZATION_DEVICE", WhisperDevice, WhisperDevice.AUTO),
        hf_token=raw.get("HF_TOKEN"),
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        chunk_mode=_choice(raw, "CHUNK_MODE", ChunkMode, ChunkMode.VAD),
        vad_threshold=_number(raw, "VAD_THRESHOLD", 0.5, minimum=0.01, maximum=0.99),
        vad_min_silence_ms=_integer(raw, "VAD_MIN_SILENCE_MS", 600, minimum=100, maximum=5000),
        vad_min_chunk_seconds=_number(raw, "VAD_MIN_CHUNK_SECONDS", 1.0, minimum=0, maximum=5),
        vad_max_chunk_seconds=_number(raw, "VAD_MAX_CHUNK_SECONDS", 15.0, minimum=5, maximum=60),
        vad_speech_pad_ms=_integer(raw, "VAD_SPEECH_PAD_MS", 200, minimum=0, maximum=1000),
        live_partials=_flag(raw, "LIVE_PARTIALS", True),
        partial_interval_seconds=_number(
            raw, "PARTIAL_INTERVAL_SECONDS", 1.5, minimum=0.5, maximum=10
        ),
        echo_dedupe_enabled=_flag(raw, "ECHO_DEDUPE_ENABLED", True),
        echo_similarity=_number(raw, "ECHO_SIMILARITY", 0.85, minimum=0.5, maximum=1),
        echo_hold_seconds=_optional_number(raw, "ECHO_HOLD_SECONDS", minimum=1, maximum=60),
        vocabulary_file=Path(raw["VOCABULARY_FILE"]) if "VOCABULARY_FILE" in raw else None,
        context_prompt_chars=_integer(raw, "CONTEXT_PROMPT_CHARS", 200, minimum=0, maximum=1000),
        low_confidence_threshold=_number(
            raw, "LOW_CONFIDENCE_THRESHOLD", 0.5, minimum=0, maximum=1
        ),
        llm_provider=raw.get("LLM_PROVIDER", "ollama"),
        ollama_url=_url(raw, "OLLAMA_URL", "http://localhost:11434"),
        ollama_model=raw.get("OLLAMA_MODEL", "qwen2.5:7b"),
        llm_max_chars=int(_number(raw, "LLM_MAX_CHARS", 12000, minimum=1000, maximum=1_000_000)),
        minutes_template=_template(raw),
        ollama_keep_alive=_duration(raw, "OLLAMA_KEEP_ALIVE", "0"),
        generate_minutes=_flag(raw, "GENERATE_MINUTES", True),
        autosave_seconds=_number(raw, "AUTOSAVE_SECONDS", 10.0, minimum=1, maximum=300),
        api_host=raw.get("API_HOST", "127.0.0.1"),
        api_port=int(_integer(raw, "API_PORT", 8765, minimum=1, maximum=65535)),
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


def _optional_number(
    raw: Mapping[str, str], key: str, *, minimum: float, maximum: float
) -> float | None:
    if key not in raw:
        return None
    return _number(raw, key, minimum, minimum=minimum, maximum=maximum)


def _integer(raw: Mapping[str, str], key: str, default: int, *, minimum: int, maximum: int) -> int:
    value = _number(raw, key, default, minimum=minimum, maximum=maximum)
    if value != int(value):
        raise ConfigError(key, raw[key], "out_of_range", min=minimum, max=maximum)
    return int(value)


def _optional_integer(
    raw: Mapping[str, str], key: str, *, minimum: int, maximum: int
) -> int | None:
    if key not in raw:
        return None
    return _integer(raw, key, minimum, minimum=minimum, maximum=maximum)


def _speaker_bounds(raw: Mapping[str, str]) -> tuple[int | None, int | None]:
    """`MIN_SPEAKERS` / `MAX_SPEAKERS` hints (1-20, empty = let the diarizer decide)."""
    low = _optional_integer(raw, "MIN_SPEAKERS", minimum=1, maximum=MAX_SPEAKERS_LIMIT)
    high = _optional_integer(raw, "MAX_SPEAKERS", minimum=1, maximum=MAX_SPEAKERS_LIMIT)
    if low is not None and high is not None and low > high:
        raise ConfigError("MIN_SPEAKERS", raw["MIN_SPEAKERS"], "out_of_range", min=1, max=high)
    return low, high


def _flag(raw: Mapping[str, str], key: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key].lower()
    if value in _TRUE or value in _FALSE:
        return value in _TRUE
    raise ConfigError(key, raw[key], "invalid_choice", allowed="true, false")


def _url(raw: Mapping[str, str], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not value.startswith(("http://", "https://")):
        raise ConfigError(key, value, "invalid_url")
    return value.rstrip("/")


def _duration(raw: Mapping[str, str], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not _DURATION.fullmatch(value):
        raise ConfigError(key, value, "invalid_duration")
    return value


def _template(raw: Mapping[str, str]) -> str:
    value = raw.get("MINUTES_TEMPLATE", DEFAULT_TEMPLATE)
    templates = bundled_templates()
    if value not in templates:
        allowed = ", ".join(templates.ids())
        raise ConfigError("MINUTES_TEMPLATE", value, "invalid_choice", allowed=allowed)
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
