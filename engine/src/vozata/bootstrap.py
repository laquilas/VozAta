"""Composition root: the only module that knows concrete providers (architecture §3).

New providers are added to a registry here; orchestrators never change.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vozata.api.action_items_job import ActionItemsJob
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
from vozata.diarization.subprocess_embedder import pyannote_embedder_from_settings
from vozata.domain import (
    AudioChunk,
    Channel,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    SessionStatus,
    TranslationTarget,
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
from vozata.minutes.session_minutes import stored_template, stored_vocabulary
from vozata.minutes.template_repository import bundled_templates
from vozata.ports import (
    AudioMixer,
    Chunker,
    Diarizer,
    DocumentExporter,
    LanguageModel,
    Localizer,
    RecoverableStore,
    SessionAudio,
    SessionObserver,
    SessionRepository,
    SpeakerEmbedder,
    TaskExporter,
    Transcriber,
    TranscriptSearch,
    Translator,
)
from vozata.qa.answerer import MeetingAnswerer
from vozata.qa.retriever import Retriever
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.settings_file import SettingsFile
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore
from vozata.transcription import openai_compatible
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.shared import SharedTranscriber
from vozata.translation import opus_mt
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
EMBEDDERS: dict[str, Callable[[Settings], SpeakerEmbedder]] = {
    "pyannote": pyannote_embedder_from_settings,  # long-lived child process (phase 15)
}
LANGUAGE_MODELS: dict[str, Callable[[Settings], LanguageModel]] = {
    "ollama": lambda settings: OllamaLanguageModel(
        settings.ollama_url, settings.ollama_model, settings.ollama_keep_alive
    ),
}

TRANSLATORS: dict[str, Callable[[Settings], Translator]] = {
    "opus_mt": lambda settings: opus_mt.from_settings(settings.translation_model_dir),
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
# Storage backends (phase 30): the only place that builds them. The `STORAGE_BACKEND` key comes
# with the SQLite backend (phase 31); until then the file backend is the only one.
STORAGE_BACKEND = "files"
REPOSITORIES: dict[str, Callable[[Settings], SessionRepository]] = {
    "files": lambda settings: FileSessionRepository(SessionStore(settings.output_dir)),
}
AUDIO_STORES: dict[str, Callable[[Settings], SessionAudio]] = {
    "files": lambda settings: FileAudioStore(
        SessionStore(settings.output_dir), settings.sample_rate
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


def _at(settings: Settings, output_dir: Path | None) -> Settings:
    return settings if output_dir is None else dataclasses.replace(settings, output_dir=output_dir)


def build_store(settings: Settings, output_dir: Path | None = None) -> SessionRepository:
    """The session repository of `OUTPUT_DIR` (or of `output_dir`, for a CLI session folder)."""
    return REPOSITORIES[STORAGE_BACKEND](_at(settings, output_dir))


def build_audio_store(settings: Settings, output_dir: Path | None = None) -> SessionAudio:
    """The audio store matching `build_store` (same `output_dir`)."""
    return AUDIO_STORES[STORAGE_BACKEND](_at(settings, output_dir))


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
    settings: Settings, store: SessionRepository, search_index: TranscriptSearch | None
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


def build_embedder_factory(settings: Settings) -> Callable[[], SpeakerEmbedder] | None:
    """The live speaker embedder (`DIARIZATION_PROVIDER`), built on the live worker's thread;
    None unless `LIVE_DIARIZATION_ENABLED`."""
    if not settings.live_diarization_enabled:
        return None
    factory = _provider(EMBEDDERS, "DIARIZATION_PROVIDER", settings.diarization_provider)
    return functools.partial(factory, settings)


def build_translator_factory(
    settings: Settings, translate_to: TranslationTarget | None = None
) -> tuple[str | None, Callable[[], Translator] | None]:
    """The live translation target and translator factory (phase 29); `(None, None)` when off.

    `translate_to` (the Start screen choice) overrides `TRANSLATE_TO`. The translator itself is
    built by the translation worker on its own thread, so a slow model load never delays capture.
    """
    target = translate_to or settings.translate_to
    if target is TranslationTarget.OFF:
        return None, None
    factory = _provider(TRANSLATORS, "TRANSLATION_PROVIDER", settings.translation_provider)
    return target.value, functools.partial(factory, settings)


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
    translate_to: TranslationTarget | None = None,
    title: str | None = None,
) -> RecordingSession:
    """A ready-to-start session; no stream is opened and no folder created until `start()`.

    Devices default to the WASAPI default microphone and the default output's loopback. Every
    PortAudio call runs on one `PortAudioThread`, closed by the session when capture ends. With a
    `shared` transcriber (`WHISPER_KEEP_LOADED`) the model stays loaded after the session unless
    minutes follow (VRAM rule). `template` (default `MINUTES_TEMPLATE`) is the minutes template,
    stored in `session.json` even when minutes are off. `vocabulary` (this meeting's terms) is
    merged with the glossary file (`vocabulary_path(settings, env_file)`), session terms first.
    `translate_to` (default `TRANSLATE_TO`) is the live translation language (phase 29); `title`
    (normalized, phase 35) is stored in the metadata.
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
    translation_target, translator_factory = build_translator_factory(settings, translate_to)
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
        embedder_factory=build_embedder_factory(settings),
        translate_to=translation_target,
        translator_factory=translator_factory,
        title=title,
    )
    return RecordingSession(
        settings,
        build_store(settings),
        build_audio_store(settings),
        components,
        observer,
        language or settings.transcription_language,
    )


class _CaptureOver:
    """The clock of a recovered session: capture ended with the crash (phase 17)."""

    def start(self) -> None:
        pass

    def now(self) -> float:
        return 0.0


def _no_transcriber() -> Transcriber:
    raise RuntimeError("A recovered session is not transcribed again")


def build_recovery_session(
    settings: Settings,
    store: SessionRepository,
    audio: SessionAudio,
    observer: SessionObserver,
    session_id: str,
) -> RecordingSession:
    """A `RecordingSession` that finishes an interrupted session (phase 17).

    Nothing is captured or transcribed; the minutes template, glossary and mix mode come from the
    session's metadata, so the result matches what its own stop would have produced. The search
    index is the one of `OUTPUT_DIR`, used only when the session lives there.
    """
    meta = store.read_meta(session_id)
    localizer = build_localizer(settings)
    template = stored_template(meta) or settings.minutes_template
    minutes = (
        build_minutes_generator(settings, localizer, template)
        if settings.generate_minutes
        else None
    )
    recorded = meta.get("settings")
    mix_value = recorded.get("MIX_MODE") if isinstance(recorded, dict) else None
    mix_mode = MixMode(mix_value) if mix_value in set(MixMode) else settings.mix_mode
    folder = store.folder(session_id)
    in_output_dir = folder is None or folder.parent.resolve() == settings.output_dir.resolve()
    components = SessionComponents(
        sources={},
        device_names={},
        clock=_CaptureOver(),
        transcriber_factory=_no_transcriber,
        mixer=MIXERS[mix_mode](),
        minutes=minutes,
        localizer=localizer,
        labeler=build_labeler(settings, localizer),
        diarizer_factory=build_diarizer_factory(settings),
        search_index=build_search_index(settings) if in_output_dir else None,
        minutes_template=template,
        vocabulary=tuple(stored_vocabulary(meta)),
        action_items=build_action_item_extractor(settings, localizer)
        if minutes is not None and settings.extract_action_items
        else None,
    )
    return RecordingSession(
        settings, store, audio, components, observer, settings.transcription_language
    )


def build_recovery(
    settings: Settings,
    output_dir: Path | None = None,
    *,
    store: SessionRepository | None = None,
    audio: SessionAudio | None = None,
    stale_after: float = 0.0,
    current: Callable[[], Settings] | None = None,
    before_finish: Callable[[], None] = lambda: None,
) -> SessionRecovery:
    """Crash recovery over `store` / `audio` (default: those of `output_dir`, else `OUTPUT_DIR`).

    `current` gives the settings each recovery uses (`serve`: the ones saved through
    `PUT /settings`); `before_finish` runs before the stop steps (`serve`: unload a kept Whisper,
    VRAM rule). `stale_after` > 0 leaves alone sessions with a recent heartbeat (CLI).
    """
    store = store or build_store(settings, output_dir)
    audio = audio or build_audio_store(settings, output_dir)
    settings_now = current or (lambda: settings)

    def session(session_id: str, observer: SessionObserver) -> RecordingSession:
        before_finish()
        return build_recovery_session(settings_now(), store, audio, observer, session_id)

    repairs = [part for part in (audio, store) if isinstance(part, RecoverableStore)]
    return SessionRecovery(store, repairs, session, stale_after)


def cli_stale_after(settings: Settings) -> float:
    """How old a heartbeat must be before the CLI treats a session as interrupted (phase 17)."""
    return 2 * settings.autosave_seconds + 5


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
    audio = build_audio_store(settings)
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
            translate_to=options.translate_to,
            title=options.title,
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
    recovery = build_recovery(  # phase 17: only sessions not live in this process
        settings,
        store=store,
        audio=audio,
        current=lambda: settings_file.current,
        before_finish=shared.release if shared is not None else lambda: None,
    )
    manager = SessionManager(
        session_factory, store, broadcaster, labeler, recovery=recovery, localizer=localizer
    )

    def answerer() -> MeetingAnswerer:
        current = manager.current
        recording = current is not None and current.status in _ACTIVE
        if shared is not None and not recording:
            shared.release()  # VRAM rule, unless a recording is using the model right now
        return build_answerer(settings_file.current, store, search_index)  # current language

    def action_item_extractor() -> ActionItemExtractor:
        current = manager.current
        recording = current is not None and current.status in _ACTIVE
        if shared is not None and not recording:
            shared.release()  # VRAM rule, as for answers
        return build_action_item_extractor(settings_file.current)  # current language

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
        extract_action_items=ActionItemsJob(
            store, action_item_extractor, labeler, broadcaster, localizer
        ),
        task_targets=lambda: task_targets(settings_file.current),
        task_exporter=lambda target: build_task_exporter(settings_file.current, target),
    )
