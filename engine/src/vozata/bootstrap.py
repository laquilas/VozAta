"""Composition root: the only module that knows concrete providers (architecture §3).

New providers are added to a registry here; orchestrators never change.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from pathlib import Path

from vozata.api.container import ApiContainer
from vozata.api.minutes_job import MinutesJob
from vozata.api.session_manager import SessionManager, StartOptions
from vozata.api.system_info import query_gpu
from vozata.api.ws import EventBroadcaster
from vozata.audio.capture import WasapiSource
from vozata.audio.catalog import WasapiCatalog
from vozata.audio.chunker import FixedWindowChunker
from vozata.audio.clock import SessionClock
from vozata.audio.devices import DeviceInfo, default_input, default_loopback, find_device
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.audio.portaudio import PortAudioThread
from vozata.audio.silero import SileroSpeechDetector
from vozata.audio.vad_chunker import VadChunker
from vozata.config import ConfigError, Settings
from vozata.domain import AudioChunk, Channel, ChunkMode, ConversationLanguage, MixMode
from vozata.export.docx import DocxExporter
from vozata.export.markdown import MarkdownExporter
from vozata.export.pdf import PdfExporter
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.template_repository import bundled_templates
from vozata.ports import (
    AudioMixer,
    Chunker,
    DocumentExporter,
    LanguageModel,
    Localizer,
    SessionObserver,
    Transcriber,
)
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.settings_file import SettingsFile
from vozata.storage.session_store import SessionStore
from vozata.transcription import openai_compatible
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.shared import SharedTranscriber

TRANSCRIBERS: dict[str, Callable[[Settings], Transcriber]] = {
    "faster_whisper": FasterWhisperTranscriber,
    "openai_compatible": openai_compatible.from_settings,
}
LANGUAGE_MODELS: dict[str, Callable[[Settings], LanguageModel]] = {
    "ollama": lambda settings: OllamaLanguageModel(
        settings.ollama_url, settings.ollama_model, settings.ollama_keep_alive
    ),
}


def _vad_chunker(
    settings: Settings, channel: Channel, on_chunk: Callable[[AudioChunk], None]
) -> Chunker:
    return VadChunker(
        channel,
        settings.sample_rate,
        on_chunk,
        SileroSpeechDetector(settings.sample_rate, settings.vad_threshold),
        min_silence=settings.vad_min_silence_ms / 1000,
        min_chunk=settings.vad_min_chunk_seconds,
        max_chunk=settings.vad_max_chunk_seconds,
        speech_pad=settings.vad_speech_pad_ms / 1000,
    )


CHUNKERS: dict[ChunkMode, Callable[[Settings, Channel, Callable[[AudioChunk], None]], Chunker]] = {
    ChunkMode.VAD: _vad_chunker,
    ChunkMode.FIXED: lambda settings, channel, on_chunk: FixedWindowChunker(
        channel, settings.chunk_seconds, settings.sample_rate, on_chunk
    ),
}
EXPORTERS: dict[str, Callable[[], DocumentExporter]] = {
    "md": MarkdownExporter,
    "docx": DocxExporter,
    "pdf": PdfExporter,
}
MIXERS: dict[MixMode, Callable[[], AudioMixer]] = {
    MixMode.MONO: MonoMixer,
    MixMode.STEREO: StereoMixer,
}
MINUTES_TEMPLATES = bundled_templates()  # validated at import (phase 20)


def _provider[T](registry: Mapping[str, T], key: str, value: str) -> T:
    if value not in registry:
        raise ConfigError(key, value, "invalid_choice", allowed=", ".join(sorted(registry)))
    return registry[value]


def build_localizer(settings: Settings) -> Localizer:
    return TomlLocalizer(settings.app_language)


def build_labeler(settings: Settings, localizer: Localizer) -> SpeakerLabeler:
    return SpeakerLabeler(localizer, settings.mic_label, settings.system_label)


def build_store(settings: Settings) -> SessionStore:
    return SessionStore(settings.output_dir)


def build_minutes_generator(
    settings: Settings, localizer: Localizer | None = None, template: str | None = None
) -> MinutesGenerator:
    """Minutes with `template` (default: `MINUTES_TEMPLATE`) in `APP_LANGUAGE`.

    Raises `UnknownTemplateError` for an id that is not bundled.
    """
    factory = _provider(LANGUAGE_MODELS, "LLM_PROVIDER", settings.llm_provider)
    template_id = template or settings.minutes_template
    localized = MINUTES_TEMPLATES.get(template_id).localized(settings.app_language)
    return MinutesGenerator(
        factory(settings), localizer or build_localizer(settings), settings.llm_max_chars, localized
    )


def build_session(
    settings: Settings,
    observer: SessionObserver,
    *,
    language: ConversationLanguage | None = None,
    mic_device: int | None = None,
    system_device: int | None = None,
    shared: SharedTranscriber | None = None,
) -> RecordingSession:
    """A ready-to-start session; no stream is opened and no folder created until `start()`.

    Devices default to the WASAPI default microphone and the default output's loopback. Every
    PortAudio call runs on one `PortAudioThread`, closed by the session when capture ends. With a
    `shared` transcriber (`WHISPER_KEEP_LOADED`) the model stays loaded after the session unless
    minutes follow (VRAM rule).
    """
    transcriber = _provider(TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)
    localizer = build_localizer(settings)
    minutes = build_minutes_generator(settings, localizer) if settings.generate_minutes else None
    try:
        audio = PortAudioThread()
    except TimeoutError:
        message = localizer.t("errors.session.audio_unavailable")
        raise SessionStartError("audio_unavailable", message) from None
    try:
        devices = _devices(audio, mic_device, system_device)
    except BaseException:
        audio.close()
        raise
    clock = SessionClock()
    components = SessionComponents(
        sources={
            channel: WasapiSource(
                device, clock, settings.sample_rate, pa=audio.pa, call_audio=audio.call
            )
            for channel, device in devices.items()
        },
        device_names={channel: device.name for channel, device in devices.items()},
        clock=clock,
        transcriber_factory=(
            (lambda: transcriber(settings))
            if shared is None
            else functools.partial(shared.lease, keep=minutes is None)
        ),
        mixer=MIXERS[settings.mix_mode](),
        minutes=minutes,
        localizer=localizer,
        labeler=build_labeler(settings, localizer),
        release=audio.close,
        chunker_factory=functools.partial(CHUNKERS[settings.chunk_mode], settings),
    )
    return RecordingSession(
        settings,
        build_store(settings),
        components,
        observer,
        language or settings.transcription_language,
    )


def _devices(
    audio: PortAudioThread, mic_device: int | None, system_device: int | None
) -> dict[Channel, DeviceInfo]:
    pa = audio.pa
    mic = audio.call(
        lambda: default_input(pa) if mic_device is None else find_device(mic_device, pa)
    )
    system = audio.call(
        lambda: default_loopback(pa) if system_device is None else find_device(system_device, pa)
    )
    return {Channel.MIC: mic, Channel.SYSTEM: system}


def build_api_container(settings: Settings, env_file: Path | None = None) -> ApiContainer:
    """Everything `api.app.create_app` needs, wired with the real providers.

    Sessions, minutes jobs and the language-model check read the current settings, so keys saved
    through `PUT /settings` apply from the next session; the others need an engine restart.
    """
    localizer = build_localizer(settings)
    labeler = build_labeler(settings, localizer)
    store = build_store(settings)
    broadcaster = EventBroadcaster()
    settings_file = SettingsFile(env_file or Path(".env"), settings)
    shared = None
    if settings.whisper_keep_loaded:
        transcriber = _provider(TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)
        shared = SharedTranscriber(lambda: transcriber(settings))

    def session_factory(observer: SessionObserver, options: StartOptions) -> RecordingSession:
        return build_session(
            settings_file.current,
            observer,
            language=options.language,
            mic_device=options.mic_device,
            system_device=options.system_device,
            shared=shared,
        )

    def minutes_generator() -> MinutesGenerator:
        if shared is not None:
            shared.release()  # VRAM rule: never Whisper and the LLM together
        return build_minutes_generator(settings_file.current, localizer)

    def llm_reachable() -> bool:
        current = settings_file.current
        model = _provider(LANGUAGE_MODELS, "LLM_PROVIDER", current.llm_provider)(current)
        try:
            return model.is_available()
        finally:
            close = getattr(model, "close", None)
            if close is not None:
                close()

    _provider(LANGUAGE_MODELS, "LLM_PROVIDER", settings.llm_provider)  # fail fast on a bad key
    return ApiContainer(
        settings=settings,
        settings_file=settings_file,
        localizer=localizer,
        labeler=labeler,
        store=store,
        broadcaster=broadcaster,
        manager=SessionManager(session_factory, store, broadcaster, labeler),
        devices=WasapiCatalog(),
        gpu_info=functools.cache(query_gpu),  # the GPU does not change while running
        llm_reachable=llm_reachable,
        regenerate_minutes=MinutesJob(store, minutes_generator, labeler, broadcaster, localizer),
        release_models=shared.release if shared is not None else lambda: None,
        exporters={name: build() for name, build in EXPORTERS.items()},
    )
