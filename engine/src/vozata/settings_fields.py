"""Every configuration key and how `GET /settings` describes it (architecture §9).

Each roadmap phase adds the keys it owns here; `config.py` parses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vozata.domain import AppLanguage, ChunkMode, ConversationLanguage, MixMode, WhisperDevice


@dataclass(frozen=True)
class Field:
    """One configuration key: its `Settings` attribute and how `GET /settings` describes it."""

    key: str
    attribute: str
    type: str  # "number" | "integer" | "string" | "bool" | "choice" | "url" | "path"
    choices: type[StrEnum] | None = None
    secret: bool = False


FIELDS: tuple[Field, ...] = (
    Field("CHUNK_SECONDS", "chunk_seconds", "number"),
    Field("SAMPLE_RATE", "sample_rate", "integer"),
    Field("APP_LANGUAGE", "app_language", "choice", AppLanguage),
    Field("TRANSCRIPTION_LANGUAGE", "transcription_language", "choice", ConversationLanguage),
    Field("MIC_LABEL", "mic_label", "string"),
    Field("SYSTEM_LABEL", "system_label", "string"),
    Field("OUTPUT_DIR", "output_dir", "path"),
    Field("MIX_MODE", "mix_mode", "choice", MixMode),
    # Transcription (phase 03)
    Field("TAIL_MARGIN_SECONDS", "tail_margin_seconds", "number"),
    Field("PAUSE_GAP_SECONDS", "pause_gap_seconds", "number"),
    Field("MAX_CARRY_SECONDS", "max_carry_seconds", "number"),
    Field("SILENCE_RMS_THRESHOLD", "silence_rms_threshold", "number"),
    Field("STT_PROVIDER", "stt_provider", "string"),
    Field("WHISPER_MODEL", "whisper_model", "string"),
    Field("WHISPER_DEVICE", "whisper_device", "choice", WhisperDevice),
    Field("WHISPER_COMPUTE_TYPE", "whisper_compute_type", "string"),
    Field("WHISPER_CPU_MODEL", "whisper_cpu_model", "string"),
    Field("WHISPER_KEEP_LOADED", "whisper_keep_loaded", "bool"),  # phase 26
    # Pause-based segmentation (phase 27)
    Field("CHUNK_MODE", "chunk_mode", "choice", ChunkMode),
    Field("VAD_THRESHOLD", "vad_threshold", "number"),
    Field("VAD_MIN_SILENCE_MS", "vad_min_silence_ms", "integer"),
    Field("VAD_MIN_CHUNK_SECONDS", "vad_min_chunk_seconds", "number"),
    Field("VAD_MAX_CHUNK_SECONDS", "vad_max_chunk_seconds", "number"),
    Field("VAD_SPEECH_PAD_MS", "vad_speech_pad_ms", "integer"),
    # Minutes (phase 04)
    Field("LLM_PROVIDER", "llm_provider", "string"),
    Field("OLLAMA_URL", "ollama_url", "url"),
    Field("OLLAMA_MODEL", "ollama_model", "string"),
    Field("LLM_MAX_CHARS", "llm_max_chars", "integer"),
    # LLM VRAM release (phase 25)
    Field("OLLAMA_KEEP_ALIVE", "ollama_keep_alive", "string"),
    # Session (phase 05)
    Field("GENERATE_MINUTES", "generate_minutes", "bool"),
    # API (phase 06)
    Field("API_HOST", "api_host", "string"),
    Field("API_PORT", "api_port", "integer"),
)
