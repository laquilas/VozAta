"""Composition root: the only module that knows concrete providers (architecture §3).

New providers are added to a registry here; orchestrators never change.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vozata.api.ask_job import AskJob
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
from vozata.diarization.subprocess_diarizer import pyannote_from_settings
from vozata.domain import (
    AudioChunk,
    Channel,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    SessionStatus,
)
from vozata.export.docx import DocxExporter
from vozata.export.markdown import MarkdownExporter
from vozata.export.pdf import PdfExporter
from vozata.export.tasks.azure_devops import AzureDevOpsExporter
from vozata.export.tasks.github import GitHubIssuesExporter
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.action_items import ActionItemExtractor
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.template_repository import bundled_templates
from vozata.ports import (
    AudioMixer,
    Chunker,
    Diarizer,
    DocumentExporter,
    LanguageModel,
    Localizer,
    SessionObserver,
    TaskExporter,
    Transcriber,
    TranscriptSearch,
)
from vozata.qa.answerer import MeetingAnswerer
from vozata.qa.retriever import Retriever
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.settings_file import SettingsFile
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore
from vozata.transcription import openai_compatible
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.shared import SharedTranscriber
from vozata.vocabulary import VocabularyStore, merge_terms

DEFAULT_VOCABULARY_FILE = "vocabulary.txt"  # next to `.env` when VOCABULARY_FILE is empty

_log = logging.getLogger(__name__)

TRANSCRIBERS: dict[str, Callable[[Settings], Transcriber]] = {
    "faster_whisper": FasterWhisperTranscriber,
    "openai_compatible": openai_compatible.from_settings,
}
DIARIZERS: dict[str, Callable[[Settings], Diarizer]] = {
    "pyannote": pyannote_from_settings,  # child process: keeps torch away from ctranslate2
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


@dataclass(frozen=True)
class TaskTarget:
    """A task export target (phase 23): offered only when `configured(settings)` is true."""

    configured: Callable[[Settings], bool]
    build: Callable[[Settings], TaskExporter]


TASK_EXPORTERS: dict[str, TaskTarget] = {
    "azure_devops": TaskTarget(
        lambda s: bool(s.azdo_org_url and s.azdo_project and s.azdo_pat),
        lambda s: AzureDevOpsExporter(s.azdo_org_url or "", s.azdo_project or "", s.azdo_pat or ""),
    ),
    "github": TaskTarget(
        lambda s: bool(s.github_repo and s.github_token),
        lambda s: GitHubIssuesExporter(s.github_repo or "", s.github_token or ""),
    ),
}
MIXERS: dict[MixMode, Callable[[], AudioMixer]] = {
    MixMode.MONO: MonoMixer,
    MixMode.STEREO: StereoMixer,
}
_ACTIVE = (SessionStatus.RECORDING, SessionStatus.PAUSED, SessionStatus.FINALIZING)
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


def build_search_index(settings: Settings) -> SearchIndex:
    return SearchIndex(settings.output_dir / "index.db")


def vocabulary_path(settings: Settings, env_file: Path | None = None) -> Path:
    """`VOCABULARY_FILE`, else `vocabulary.txt` next to the `.env` file (phase 19)."""
    if settings.vocabulary_file is not None:
        return settings.vocabulary_file
    return (env_file or Path(".env")).parent / DEFAULT_VOCABULARY_FILE


def session_vocabulary(
    settings: Settings, session_terms: Sequence[str], env_file: Path | None = None
) -> list[str]:
    """The session terms, then the glossary; an unreadable glossary is logged and skipped."""
    try:
        glossary = VocabularyStore(vocabulary_path(settings, env_file)).read()
    except (OSError, UnicodeDecodeError) as error:
        _log.warning("Reading the vocabulary file failed: %s", error)
        glossary = []
    return merge_terms(session_terms, glossary)


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


def build_action_item_extractor(
    settings: Settings, localizer: Localizer | None = None
) -> ActionItemExtractor:
    """Action items in `APP_LANGUAGE` from the `LLM_PROVIDER` model (phase 23)."""
    llm = _provider(LANGUAGE_MODELS, "LLM_PROVIDER", settings.llm_provider)(settings)
    return ActionItemExtractor(llm, localizer or build_localizer(settings), settings.llm_max_chars)


def build_answerer(
    settings: Settings, store: SessionStore, search_index: TranscriptSearch | None
) -> MeetingAnswerer:
    """Answers about the meetings (phase 24) in `APP_LANGUAGE`, within `LLM_MAX_CHARS`."""
    llm = _provider(LANGUAGE_MODELS, "LLM_PROVIDER", settings.llm_provider)(settings)
    localizer = build_localizer(settings)
    labeler = build_labeler(settings, localizer)
    retriever = Retriever(store, search_index, labeler, localizer, settings.llm_max_chars)
    return MeetingAnswerer(llm, retriever, localizer)


def task_targets(settings: Settings) -> list[str]:
    """The configured task export targets, in registry order (phase 23)."""
    return [name for name, target in TASK_EXPORTERS.items() if target.configured(settings)]


def build_task_exporter(settings: Settings, target: str) -> TaskExporter | None:
    """The exporter for `target`; None when it is unknown or not configured."""
    entry = TASK_EXPORTERS.get(target)
    if entry is None or not entry.configured(settings):
        return None
    return entry.build(settings)


def build_diarizer_factory(settings: Settings) -> Callable[[], Diarizer] | None:
    """The configured diarizer, built only when a session needs it; None when disabled."""
    if not settings.diarization_enabled:
        return None
    _provider(DIARIZERS, "DIARIZATION_PROVIDER", settings.diarization_provider)  # fail fast
    return functools.partial(build_diarizer, settings)


def build_diarizer(settings: Settings) -> Diarizer:
    """The `DIARIZATION_PROVIDER` diarizer, whether or not `DIARIZATION_ENABLED` is set."""
    return _provider(DIARIZERS, "DIARIZATION_PROVIDER", settings.diarization_provider)(settings)


def build_session(
    settings: Settings,
    observer: SessionObserver,
    *,
    language: ConversationLanguage | None = None,
    mic_device: int | None = None,
    system_device: int | None = None,
    shared: SharedTranscriber | None = None,
    template: str | None = None,
    vocabulary: Sequence[str] = (),
    env_file: Path | None = None,
) -> RecordingSession:
    """A ready-to-start session; no stream is opened and no folder created until `start()`.

    Devices default to the WASAPI default microphone and the default output's loopback. Every
    PortAudio call runs on one `PortAudioThread`, closed by the session when capture ends. With a
    `shared` transcriber (`WHISPER_KEEP_LOADED`) the model stays loaded after the session unless
    minutes follow (VRAM rule). `template` (default `MINUTES_TEMPLATE`) is the minutes template,
    stored in `session.json` even when minutes are off. `vocabulary` (this meeting's terms) is
    merged with the glossary file (`vocabulary_path(settings, env_file)`), session terms first.
    """
    transcriber = _provider(TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)
    localizer = build_localizer(settings)
    template = template or settings.minutes_template
    MINUTES_TEMPLATES.get(template)  # an unknown template fails before any device is opened
    minutes = (
        build_minutes_generator(settings, localizer, template)
        if settings.generate_minutes
        else None
    )
    diarizer_factory = build_diarizer_factory(settings)
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
            else functools.partial(shared.lease, keep=minutes is None and diarizer_factory is None)
        ),
        mixer=MIXERS[settings.mix_mode](),
        minutes=minutes,
        localizer=localizer,
        labeler=build_labeler(settings, localizer),
        release=audio.close,
        chunker_factory=functools.partial(CHUNKERS[settings.chunk_mode], settings),
        diarizer_factory=diarizer_factory,
        search_index=build_search_index(settings),
        minutes_template=template,
        vocabulary=tuple(session_vocabulary(settings, vocabulary, env_file)),
        action_items=build_action_item_extractor(settings, localizer)
        if minutes is not None and settings.extract_action_items
        else None,
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
    env_file = env_file or Path(".env")
    settings_file = SettingsFile(env_file, settings)
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
            template=options.template,
            vocabulary=options.vocabulary,
            env_file=env_file,
            shared=shared,
        )

    def minutes_generator(template: str | None = None) -> MinutesGenerator:
        if shared is not None:
            shared.release()  # VRAM rule: never Whisper and the LLM together
        return build_minutes_generator(settings_file.current, None, template)  # current language

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
    search_index = build_search_index(settings)
    manager = SessionManager(session_factory, store, broadcaster, labeler)

    def answerer() -> MeetingAnswerer:
        current = manager.current
        recording = current is not None and current.status in _ACTIVE
        if shared is not None and not recording:
            shared.release()  # VRAM rule, unless a recording is using the model right now
        return build_answerer(settings_file.current, store, search_index)  # current language

    threading.Thread(
        target=search_index.ensure, args=(store,), name="search-index", daemon=True
    ).start()  # sessions recorded before phase 22 become searchable
    return ApiContainer(
        settings=settings,
        settings_file=settings_file,
        localizer=localizer,
        labeler=labeler,
        store=store,
        broadcaster=broadcaster,
        manager=manager,
        devices=WasapiCatalog(),
        gpu_info=functools.cache(query_gpu),  # the GPU does not change while running
        llm_reachable=llm_reachable,
        regenerate_minutes=MinutesJob(store, minutes_generator, labeler, broadcaster, localizer),
        release_models=shared.release if shared is not None else lambda: None,
        exporters={name: build() for name, build in EXPORTERS.items()},
        search_index=search_index,
        vocabulary_file=lambda: vocabulary_path(settings_file.current, env_file),
        ask=AskJob(answerer, broadcaster, localizer),
    )
