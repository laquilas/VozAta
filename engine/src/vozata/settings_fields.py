"""Every configuration key and how `GET /settings` describes it (architecture §9).

Each roadmap phase adds the keys it owns here; `config.py` parses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vozata.domain import (
    AppLanguage,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    StorageBackend,
    TranslationTarget,
    WhisperDevice,
)
from vozata.minutes.template_repository import bundled_templates

# The bundled minutes template ids as choices, so the settings page offers a list (phase 20).
MinutesTemplateId = StrEnum("MinutesTemplateId", [(i, i) for i in bundled_templates().ids()])


@dataclass(frozen=True)
class Field:
    """One configuration key: its `Settings` attribute and how `GET /settings` describes it."""

    key: str
    attribute: str
    type: str  # "number" | "integer" | "string" | "bool" | "choice" | "url" | "path"
    choices: type[StrEnum] | None = None
    secret: bool = False
    group: str = "general"  # settings page section, in GROUPS order
    applies: str = "next_session"  # or "restart": read once when the engine starts
    # The `GET /settings/options` list the settings page offers for this key (phase 38).
    options_source: str | None = None


GROUPS = (
    "general",
    "audio",
    "segmentation",
    "transcription",
    "speakers",
    "minutes",
    "tasks",
    "api",
)

FIELDS: tuple[Field, ...] = (
    Field("CHUNK_SECONDS", "chunk_seconds", "number", group="segmentation"),
    Field("SAMPLE_RATE", "sample_rate", "integer", group="audio", applies="restart"),
    Field("APP_LANGUAGE", "app_language", "choice", AppLanguage, group="general"),
    Field(
        "TRANSCRIPTION_LANGUAGE",
        "transcription_language",
        "choice",
        ConversationLanguage,
        group="general",
    ),
    Field("MIC_LABEL", "mic_label", "string", group="general"),
    Field("SYSTEM_LABEL", "system_label", "string", group="general"),
    Field("OUTPUT_DIR", "output_dir", "path", group="general", applies="restart"),
    # Storage (phase 31)
    Field(
        "STORAGE_BACKEND",
        "storage_backend",
        "choice",
        StorageBackend,
        group="general",
        applies="restart",
    ),
    Field("DATABASE_PATH", "database_path", "path", group="general", applies="restart"),
    Field("MIX_MODE", "mix_mode", "choice", MixMode, group="audio"),
    # Transcription (phase 03)
    Field("TAIL_MARGIN_SECONDS", "tail_margin_seconds", "number", group="transcription"),
    Field("PAUSE_GAP_SECONDS", "pause_gap_seconds", "number", group="transcription"),
    Field("MAX_CARRY_SECONDS", "max_carry_seconds", "number", group="transcription"),
    Field("SILENCE_RMS_THRESHOLD", "silence_rms_threshold", "number", group="transcription"),
    Field(
        "STT_PROVIDER",
        "stt_provider",
        "string",
        group="transcription",
        applies="restart",
        options_source="stt_providers",
    ),
    Field(
        "WHISPER_MODEL",
        "whisper_model",
        "string",
        group="transcription",
        applies="restart",
        options_source="whisper_models",
    ),
    Field(
        "WHISPER_DEVICE",
        "whisper_device",
        "choice",
        WhisperDevice,
        group="transcription",
        applies="restart",
        options_source="devices",
    ),
    Field(
        "WHISPER_COMPUTE_TYPE",
        "whisper_compute_type",
        "string",
        group="transcription",
        applies="restart",
        options_source="compute_types",
    ),
    Field(
        "WHISPER_CPU_MODEL",
        "whisper_cpu_model",
        "string",
        group="transcription",
        applies="restart",
        options_source="whisper_models",
    ),
    Field(
        "WHISPER_KEEP_LOADED",
        "whisper_keep_loaded",
        "bool",
        group="transcription",
        applies="restart",
    ),  # phase 26
    # External STT API (phase 12)
    Field("OPENAI_STT_URL", "openai_stt_url", "url", group="transcription"),
    Field("OPENAI_STT_KEY", "openai_stt_key", "string", secret=True, group="transcription"),
    Field("OPENAI_STT_MODEL", "openai_stt_model", "string", group="transcription"),
    # Speaker identification (phase 14)
    Field("DIARIZATION_ENABLED", "diarization_enabled", "bool", group="speakers"),
    Field(
        "DIARIZATION_PROVIDER",
        "diarization_provider",
        "string",
        group="speakers",
        options_source="diarization_providers",
    ),
    Field(
        "DIARIZATION_DEVICE",
        "diarization_device",
        "choice",
        WhisperDevice,
        group="speakers",
        options_source="devices",
    ),
    Field("HF_TOKEN", "hf_token", "string", secret=True, group="speakers"),
    Field("MIN_SPEAKERS", "min_speakers", "integer", group="speakers"),
    Field("MAX_SPEAKERS", "max_speakers", "integer", group="speakers"),
    # Live speaker identification (phase 15)
    Field("LIVE_DIARIZATION_ENABLED", "live_diarization_enabled", "bool", group="speakers"),
    Field(
        "SPEAKER_SIMILARITY_THRESHOLD", "speaker_similarity_threshold", "number", group="speakers"
    ),
    # Pause-based segmentation (phase 27)
    Field("CHUNK_MODE", "chunk_mode", "choice", ChunkMode, group="segmentation"),
    Field("VAD_THRESHOLD", "vad_threshold", "number", group="segmentation"),
    Field("VAD_MIN_SILENCE_MS", "vad_min_silence_ms", "integer", group="segmentation"),
    Field("VAD_MIN_CHUNK_SECONDS", "vad_min_chunk_seconds", "number", group="segmentation"),
    Field("VAD_MAX_CHUNK_SECONDS", "vad_max_chunk_seconds", "number", group="segmentation"),
    Field("VAD_SPEECH_PAD_MS", "vad_speech_pad_ms", "integer", group="segmentation"),
    # Live interim text (phase 28)
    Field("LIVE_PARTIALS", "live_partials", "bool", group="transcription"),
    Field("PARTIAL_INTERVAL_SECONDS", "partial_interval_seconds", "number", group="transcription"),
    # Echo dedupe (phase 18)
    Field("ECHO_DEDUPE_ENABLED", "echo_dedupe_enabled", "bool", group="transcription"),
    Field("ECHO_SIMILARITY", "echo_similarity", "number", group="transcription"),
    Field("ECHO_HOLD_SECONDS", "echo_hold_seconds", "number", group="transcription"),
    # Custom vocabulary (phase 19)
    Field("VOCABULARY_FILE", "vocabulary_file", "path", group="transcription"),
    Field("CONTEXT_PROMPT_CHARS", "context_prompt_chars", "integer", group="transcription"),
    # Editable transcript (phase 21)
    Field("LOW_CONFIDENCE_THRESHOLD", "low_confidence_threshold", "number", group="transcription"),
    # Live translation (phase 29)
    Field("TRANSLATE_TO", "translate_to", "choice", TranslationTarget, group="transcription"),
    Field(
        "TRANSLATION_PROVIDER",
        "translation_provider",
        "string",
        group="transcription",
        options_source="translation_providers",
    ),
    Field("TRANSLATION_MODEL_DIR", "translation_model_dir", "path", group="transcription"),
    # Minutes (phase 04)
    Field(
        "LLM_PROVIDER", "llm_provider", "string", group="minutes", options_source="llm_providers"
    ),
    Field("OLLAMA_URL", "ollama_url", "url", group="minutes"),
    Field(
        "OLLAMA_MODEL", "ollama_model", "string", group="minutes", options_source="ollama_models"
    ),
    Field("LLM_MAX_CHARS", "llm_max_chars", "integer", group="minutes"),
    # Minutes templates (phase 20)
    Field("MINUTES_TEMPLATE", "minutes_template", "choice", MinutesTemplateId, group="minutes"),
    # LLM VRAM release (phase 25)
    Field("OLLAMA_KEEP_ALIVE", "ollama_keep_alive", "string", group="minutes"),
    # Action items export (phase 23)
    Field("EXTRACT_ACTION_ITEMS", "extract_action_items", "bool", group="minutes"),
    Field("AZDO_ORG_URL", "azdo_org_url", "url", group="tasks"),
    Field("AZDO_PROJECT", "azdo_project", "string", group="tasks"),
    Field("AZDO_PAT", "azdo_pat", "string", secret=True, group="tasks"),
    Field("GITHUB_REPO", "github_repo", "string", group="tasks"),
    Field("GITHUB_TOKEN", "github_token", "string", secret=True, group="tasks"),
    # Session (phase 05)
    Field("GENERATE_MINUTES", "generate_minutes", "bool", group="general"),
    # Crash recovery (phase 17)
    Field("AUTOSAVE_SECONDS", "autosave_seconds", "number", group="general"),
    # API (phase 06)
    Field("API_HOST", "api_host", "string", group="api", applies="restart"),
    Field("API_PORT", "api_port", "integer", group="api", applies="restart"),
)
