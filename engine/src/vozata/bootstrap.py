"""Composition root: the only module that knows concrete providers (architecture §3).

New providers are added to a registry here; orchestrators never change.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import logging
import os
import threading
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vozata.api.action_items_job import ActionItemsJob
from vozata.api.ask_job import AskJob
from vozata.api.container import ApiContainer
from vozata.api.migration_job import MigrationJob
from vozata.api.minutes_job import MinutesJob
from vozata.api.session_manager import SessionManager, StartOptions, session_observer
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
from vozata.connection_checks import ConnectionChecks
from vozata.diarization.embedder import MODEL as EMBEDDING_MODEL
from vozata.diarization.pyannote import MODEL as DIARIZATION_MODEL
from vozata.diarization.subprocess_diarizer import pyannote_from_settings
from vozata.diarization.subprocess_embedder import pyannote_embedder_from_settings
from vozata.domain import (
    AudioChunk,
    Channel,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    SessionStatus,
    StorageBackend,
    StorageInfo,
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
    BundleImporter,
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
from vozata.processing.gpu_gate import GpuGate, GpuUsage, GpuUser, gpu_usage
from vozata.processing.job import ProcessingJob, StepKind
from vozata.processing.live_lease import LiveModelTurn
from vozata.processing.queue import ProcessingQueue, ProcessingState
from vozata.qa.answerer import MeetingAnswerer
from vozata.qa.retriever import Retriever
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.session_finisher import SessionFinisher
from vozata.session_title import stored_title
from vozata.settings_file import SettingsFile
from vozata.settings_options import SettingsOptions
from vozata.storage.audio_cache import WavCache
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.bundle_import import FileBundleImporter
from vozata.storage.files.folder import open_session_folder as open_files_folder
from vozata.storage.files.recycle_bin import Send2TrashRecycler
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.migration import FolderImporter
from vozata.storage.recovery import SessionRecovery
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_folder import SessionFolder
from vozata.storage.session_store import SessionStore
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.bundle_import import SqliteBundleImporter
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.location import onedrive_root
from vozata.storage.sqlite.repository import SqliteSessionRepository
from vozata.storage.sqlite.search import SqliteSearch
from vozata.transcription import openai_compatible
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.shared import SharedTranscriber
from vozata.translation import opus_mt
from vozata.vocabulary import VocabularyStore, merge_terms

DEFAULT_VOCABULARY_FILE = "vocabulary.txt"  # next to `.env` when VOCABULARY_FILE is empty
AUDIO_CACHE_DIR = "cache"  # in `OUTPUT_DIR` (phase 32)

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
# Storage backends (phases 30-32), chosen by `STORAGE_BACKEND`: the only place that builds them.
# `sqlite` keeps the audio in the database too (phase 32); `files` keeps WAVs in `OUTPUT_DIR/<id>/`.
REPOSITORIES: dict[StorageBackend, Callable[[Settings], SessionRepository]] = {
    StorageBackend.SQLITE: lambda settings: SqliteSessionRepository(
        open_database(settings), settings.output_dir
    ),
    StorageBackend.FILES: lambda settings: FileSessionRepository(
        SessionStore(settings.output_dir),
        Send2TrashRecycler(),  # deleted folders (phase 36)
    ),
}
AUDIO_STORES: dict[StorageBackend, Callable[[Settings], SessionAudio]] = {
    StorageBackend.SQLITE: lambda settings: SqliteAudioStore(
        open_database(settings),
        settings.sample_rate,
        MIXERS[settings.mix_mode](),
        audio_cache(settings),
    ),
    StorageBackend.FILES: lambda settings: FileAudioStore(
        SessionStore(settings.output_dir),
        settings.sample_rate,
        Send2TrashRecycler(),  # discarded audio (phase 39)
    ),
}
SEARCHES: dict[StorageBackend, Callable[[Settings], SqliteSearch | SearchIndex]] = {
    StorageBackend.SQLITE: lambda settings: SqliteSearch(open_database(settings)),
    StorageBackend.FILES: lambda settings: SearchIndex(settings.output_dir / "index.db"),
}
_databases: dict[Path, Database] = {}  # one per file in this process, shared by every user
_databases_lock = threading.Lock()
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


def open_database(settings: Settings) -> Database:
    """The database of `settings.database_file`, opened (and migrated) once per process.

    Opening a database in a OneDrive folder logs a warning (also shown by `GET /health`).
    """
    path = settings.database_file
    key = Path(os.path.normcase(os.path.abspath(path)))
    with _databases_lock:
        database = _databases.get(key)
        if database is None:
            root = onedrive_root(path, settings.onedrive_roots)
            if root is not None:
                _log.warning(
                    "The database %s is in the OneDrive folder %s: sync can lock or corrupt it "
                    "while the engine runs. Set DATABASE_PATH to a folder outside OneDrive.",
                    path,
                    root,
                )
            database = _databases[key] = Database(path)
        return database


def close_databases() -> None:
    """Close every database this process opened (tests; the engine keeps them open)."""
    with _databases_lock:
        databases = list(_databases.values())
        _databases.clear()
    for database in databases:
        database.close()


def audio_cache(settings: Settings) -> WavCache:
    """`OUTPUT_DIR/cache`: WAVs built from the database, up to `AUDIO_CACHE_MB` (phase 32)."""
    return WavCache(settings.output_dir / AUDIO_CACHE_DIR, settings.audio_cache_mb * 1024 * 1024)


def clean_audio_cache(settings: Settings) -> None:
    """Trim the WAV cache to its limit (engine start); a failure is only logged."""
    if settings.storage_backend is not StorageBackend.SQLITE:
        return
    try:
        audio_cache(settings).clean()
    except OSError:
        _log.exception("Cleaning the audio cache failed")


def storage_info(settings: Settings) -> StorageInfo:
    """The backend, its database file (SQLite) and the OneDrive root that holds it, if any."""
    if settings.storage_backend is not StorageBackend.SQLITE:
        return StorageInfo(settings.storage_backend.value)
    path = settings.database_file
    return StorageInfo(
        settings.storage_backend.value, path, onedrive_root(path, settings.onedrive_roots)
    )


def build_store(settings: Settings, output_dir: Path | None = None) -> SessionRepository:
    """The session repository of `OUTPUT_DIR` (or of `output_dir`, for a CLI session folder).

    With `sqlite` and an empty `DATABASE_PATH`, the database is `vozata.db` in that folder.
    """
    return REPOSITORIES[settings.storage_backend](_at(settings, output_dir))


def build_audio_store(settings: Settings, output_dir: Path | None = None) -> SessionAudio:
    """The audio store matching `build_store` (same `output_dir`)."""
    return AUDIO_STORES[settings.storage_backend](_at(settings, output_dir))


def build_folder_importer(settings: Settings) -> FolderImporter | None:
    """The import of the session folders of `OUTPUT_DIR` into `vozata.db` (phase 33); None
    with `STORAGE_BACKEND=files` (nothing to import into)."""
    repository = build_store(settings)
    audio = build_audio_store(settings)
    if not isinstance(repository, SqliteSessionRepository) or not isinstance(
        audio, SqliteAudioStore
    ):
        return None
    files = FileSessionRepository(SessionStore(settings.output_dir))
    return FolderImporter(
        settings.output_dir,
        files,
        FileAudioStore(files.store, settings.sample_rate),
        repository,
        audio,
        settings.sample_rate,
    )


def build_bundle_importer(settings: Settings) -> BundleImporter:
    """Meeting ZIPs (phase 39) into the configured storage backend."""
    repository = build_store(settings)
    audio = build_audio_store(settings)
    if isinstance(repository, SqliteSessionRepository) and isinstance(audio, SqliteAudioStore):
        return SqliteBundleImporter(repository, audio, settings.sample_rate)
    if not isinstance(repository, FileSessionRepository) or not isinstance(audio, FileAudioStore):
        raise TypeError(f"no meeting import for {type(repository).__name__}")
    return FileBundleImporter(repository, audio, MIXERS[settings.mix_mode]())


def build_migration_job(
    settings: Settings, manager: SessionManager, broadcaster: EventBroadcaster, localizer: Localizer
) -> MigrationJob | None:
    """The folder import as a background job of `serve`: it waits while a session is busy and,
    when it imported interrupted recordings, offers to recover them (`recovery_available`)."""
    importer = build_folder_importer(settings)
    if importer is None:
        return None

    def offer_recovery() -> None:
        interrupted = manager.interrupted_sessions()
        if interrupted:
            broadcaster.publish("recovery_available", None, {"session_ids": interrupted})

    return MigrationJob(
        importer, broadcaster, localizer, should_pause=lambda: manager.busy, on_done=offer_recovery
    )


def build_search_index(settings: Settings) -> SqliteSearch | SearchIndex:
    """`segments_fts` in the database (`sqlite`) or `OUTPUT_DIR/index.db` (`files`)."""
    return SEARCHES[settings.storage_backend](settings)


def open_session_folder(settings: Settings, session_dir: Path) -> SessionFolder:
    """A session folder named on the command line (`minutes`, `diarize`), in the storage of
    its parent folder."""
    path = session_dir.resolve()
    if settings.storage_backend is StorageBackend.FILES:
        return open_files_folder(path, settings.sample_rate)
    at = _at(settings, path.parent)
    database = at.database_file.resolve()
    return SessionFolder(path, build_store(at), build_audio_store(at), database, database)


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
    gate: GpuGate | None = None,
    gpu_usage: GpuUsage | None = None,
    live_models: LiveModelTurn | None = None,
    live_transcription: bool | None = None,
) -> RecordingSession:
    """A ready-to-start session; no stream is opened and no folder created until `start()`.

    Devices default to the WASAPI default microphone and the default output's loopback. Every
    PortAudio call runs on one `PortAudioThread`, closed by the session when capture ends. With a
    `shared` transcriber (`WHISPER_KEEP_LOADED`) the model stays loaded after the session unless
    minutes follow (VRAM rule). `template` (default `MINUTES_TEMPLATE`) is the minutes template,
    stored in `session.json` even when minutes are off. `vocabulary` (this meeting's terms) is
    merged with the glossary file (`vocabulary_path(settings, env_file)`), session terms first.
    `translate_to` (default `TRANSLATE_TO`) is the live translation language (phase 29); `title`
    (normalized, phase 35) is stored in the metadata. With a `gate` (`serve`), the session holds
    its live GPU priority while recording when `gpu_usage` says its speech or speaker model runs on
    the local GPU (phase 40); with `live_models` its models load only once the previous
    session's abandoned pipeline closed. `live_transcription` (default `LIVE_TRANSCRIPTION`,
    phase 41) is the per-recording option; it is stored in `session.json`.
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
        gate=gate,
        gpu_usage=gpu_usage,
        live_models=live_models,
        live_transcription=settings.live_transcription
        if live_transcription is None
        else live_transcription,
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


def _stored_components(
    settings: Settings,
    store: SessionRepository,
    session_id: str,
    models: Collection[StepKind] | None = None,
) -> tuple[SessionComponents, dict[str, Any]]:
    """The stop-step components of a stored session, and its metadata.

    Nothing is captured or transcribed; the minutes template, glossary and mix mode come from
    the session's metadata, so the result matches what its own stop would have produced. The
    search index is the one of `OUTPUT_DIR`, used only when the session lives there. `models`
    names the steps whose model is built (`diarize`: the diarizer, `minutes`: the minutes
    generator, `action_items`: the extractor; each its own language model client); None builds
    every configured one, an empty collection none (phase 40: one step per attempt).
    """
    wanted = set(StepKind) if models is None else set(models)
    meta = store.read_meta(session_id)
    localizer = build_localizer(settings)
    template = stored_template(meta) or settings.minutes_template
    minutes = (
        build_minutes_generator(settings, localizer, template)
        if settings.generate_minutes and StepKind.MINUTES in wanted
        else None
    )
    extract = settings.generate_minutes and settings.extract_action_items
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
        diarizer_factory=build_diarizer_factory(settings) if StepKind.DIARIZE in wanted else None,
        search_index=build_search_index(settings) if in_output_dir else None,
        minutes_template=template,
        vocabulary=tuple(stored_vocabulary(meta)),
        action_items=build_action_item_extractor(settings, localizer)
        if extract and StepKind.ACTION_ITEMS in wanted
        else None,
    )
    return components, meta


def build_finisher(
    settings: Settings,
    store: SessionRepository,
    audio: SessionAudio,
    observer: SessionObserver,
    session_id: str,
    models: Collection[StepKind] | None = None,
) -> SessionFinisher:
    """The stop steps of a stored session (phase 40), with the components of its metadata.

    The title is read from `session.json` each time the minutes are written, so a rename made
    while the session waits for its turn is used. `models` limits the models built to those of
    the named steps (None: all; empty: none, so only `mix`, `index` and `ended` do anything);
    `SessionFinisher.close()` closes the language model clients built.
    """
    components, meta = _stored_components(settings, store, session_id, models)
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    return SessionFinisher(
        settings,
        store,
        audio,
        components,
        observer,
        session_id,
        LanguageLock(language, lambda detected: None),
        lambda: stored_title(store.read_meta(session_id)),
    )


def build_recovery(
    settings: Settings,
    output_dir: Path | None = None,
    *,
    store: SessionRepository | None = None,
    audio: SessionAudio | None = None,
    stale_after: float = 0.0,
) -> SessionRecovery:
    """Crash recovery over `store` / `audio` (default: those of `output_dir`, else `OUTPUT_DIR`):
    finds `interrupted` sessions and repairs their files; their processing job finishes them.
    `stale_after` > 0 leaves alone sessions with a recent heartbeat (CLI)."""
    store = store or build_store(settings, output_dir)
    audio = audio or build_audio_store(settings, output_dir)
    repairs = [part for part in (audio, store) if isinstance(part, RecoverableStore)]
    return SessionRecovery(store, repairs, stale_after)


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


def hf_hub_cache() -> Path:
    """Where Hugging Face models (Whisper, pyannote) are downloaded (`HF_HOME` / `HF_HUB_CACHE`)."""
    try:
        from huggingface_hub import constants
    except ImportError:  # pragma: no cover - installed with faster-whisper
        return Path.home() / ".cache" / "huggingface" / "hub"
    return Path(constants.HF_HUB_CACHE)


def build_setting_options(
    settings_now: Callable[[], Settings], gpu_available: Callable[[], bool]
) -> SettingsOptions:
    """The Config page lists (phase 38): registry keys, cached models, Ollama's pulled models."""
    providers = {
        "stt_providers": list(TRANSCRIBERS),
        "llm_providers": list(LANGUAGE_MODELS),
        "diarization_providers": list(DIARIZERS),
        "translation_providers": list(TRANSLATORS),
    }
    return SettingsOptions(
        providers, hf_hub_cache(), lambda: settings_now().ollama_url, gpu_available
    )


def build_api_container(settings: Settings, env_file: Path | None = None) -> ApiContainer:
    """Everything `api.app.create_app` needs, wired with the real providers.

    Sessions, minutes jobs and the language-model check read the current settings, so keys saved
    through `PUT /settings` apply from the next session; the others need an engine restart.
    """
    localizer = build_localizer(settings)
    labeler = build_labeler(settings, localizer)
    store = build_store(settings)
    audio = build_audio_store(settings)
    clean_audio_cache(settings)
    broadcaster = EventBroadcaster()
    env_file = env_file or Path(".env")
    settings_file = SettingsFile(env_file, settings)
    shared = None
    if settings.whisper_keep_loaded:
        transcriber = _provider(TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)
        shared = SharedTranscriber(lambda: transcriber(settings))
    gpu_info = functools.cache(query_gpu)  # the GPU does not change while running
    gate = GpuGate()  # phase 40: live recordings pre-empt the queue's GPU steps
    live_models = LiveModelTurn()  # a new recording loads its models once the last one closed

    def usage(current: Settings) -> GpuUsage:
        return gpu_usage(current, gpu_info().available)

    def publish_processing(state: ProcessingState) -> None:
        broadcaster.publish("processing", state.session_id, state.to_payload())

    queue = ProcessingQueue(gate, publish_processing)
    queue.start()

    def job_factory(session_id: str, repair: bool, closed: threading.Event | None) -> ProcessingJob:
        current = settings_file.current
        from vozata.bootstrap_processing import build_processing_job  # imports this module

        observer = session_observer(broadcaster, labeler, session_id)
        return build_processing_job(
            current,
            store,
            audio,
            observer,
            session_id,
            repair=repair,
            closed=closed,
            gate_usage=usage(current),
            shared=shared,
        )

    def session_factory(observer: SessionObserver, options: StartOptions) -> RecordingSession:
        current = settings_file.current
        return build_session(
            current,
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
            gate=gate,
            gpu_usage=usage(current),
            live_models=live_models,
            live_transcription=options.live_transcription,
        )

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
    recovery = build_recovery(settings, store=store, audio=audio)  # 17: sessions not live here
    manager = SessionManager(
        session_factory,
        store,
        broadcaster,
        labeler,
        recovery=recovery,
        queue=queue,
        job_factory=job_factory,
    )

    def free_whisper() -> None:
        """VRAM rule: unload the kept Whisper before the language model loads, unless a recording
        is using it right now (asked under its lease, the unload would still happen when the
        recording ends, dropping a model it keeps loaded)."""
        current = manager.current
        recording = current is not None and current.status in _ACTIVE
        if shared is not None and not recording:
            shared.release()

    def minutes_generator(template: str | None = None) -> MinutesGenerator:
        free_whisper()
        return build_minutes_generator(settings_file.current, None, template)  # current language

    def answerer() -> MeetingAnswerer:
        free_whisper()
        return build_answerer(settings_file.current, store, search_index)  # current language

    def action_item_extractor() -> ActionItemExtractor:
        free_whisper()
        return build_action_item_extractor(settings_file.current)  # current language

    def llm_on_gpu() -> bool:
        return usage(settings_file.current).llm

    def check_priority(current: Settings) -> AbstractContextManager[None]:
        return gate.priority(GpuUser.CHECK) if usage(current).llm else contextlib.nullcontext()

    def index(session_id: str) -> None:
        search_index.index_session(session_id, store.load_transcript(session_id))

    options = build_setting_options(lambda: settings_file.current, lambda: gpu_info().available)
    threading.Thread(
        target=search_index.ensure, args=(store,), name="search-index", daemon=True
    ).start()  # sessions recorded before phase 22 become searchable
    migration = build_migration_job(settings, manager, broadcaster, localizer)  # started by the app
    return ApiContainer(
        settings=settings,
        settings_file=settings_file,
        localizer=localizer,
        labeler=labeler,
        store=store,
        broadcaster=broadcaster,
        manager=manager,
        devices=WasapiCatalog(),
        gpu_info=gpu_info,
        llm_reachable=llm_reachable,
        regenerate_minutes=MinutesJob(
            store,
            minutes_generator,
            labeler,
            broadcaster,
            localizer,
            queue=queue,
            uses_gpu=llm_on_gpu,
            index=index,
        ),
        release_models=shared.release if shared is not None else lambda: None,
        stop_processing=queue.stop,
        exporters={name: build() for name, build in EXPORTERS.items()},
        search_index=search_index,
        vocabulary_file=lambda: vocabulary_path(settings_file.current, env_file),
        ask=AskJob(answerer, broadcaster, localizer, gate=gate, uses_gpu=llm_on_gpu),
        extract_action_items=ActionItemsJob(
            store,
            action_item_extractor,
            labeler,
            broadcaster,
            localizer,
            queue=queue,
            uses_gpu=llm_on_gpu,
            index=index,
        ),
        task_targets=lambda: task_targets(settings_file.current),
        task_exporter=lambda target: build_task_exporter(settings_file.current, target),
        storage=storage_info(settings),
        audio=audio,
        audio_cache=audio.cache if isinstance(audio, SqliteAudioStore) else None,
        migration=migration,
        bundle_importer=build_bundle_importer(settings),
        setting_options=options.collect,
        connection_check=ConnectionChecks(
            (DIARIZATION_MODEL, EMBEDDING_MODEL), priority=check_priority
        ).run,
    )
