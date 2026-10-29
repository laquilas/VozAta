"""Everything the API routes depend on, built by `bootstrap.build_api_container` (tests: fakes)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from vozata.api.migration_job import MigrationJob
from vozata.api.partial_minutes_job import PartialMinutesJob
from vozata.api.request_log import RequestLog
from vozata.api.session_manager import SessionManager
from vozata.api.system_info import GpuInfo
from vozata.api.ws import EventBroadcaster
from vozata.audio.devices import DeviceInfo
from vozata.config import Settings
from vozata.connection_checks import CheckResult, CheckTarget
from vozata.domain import StorageBackend, StorageInfo
from vozata.labels import SpeakerLabeler
from vozata.minutes.template_repository import TemplateRepository, bundled_templates
from vozata.models.tracker import DownloadTracker
from vozata.ports import (
    AudioCache,
    BundleImporter,
    DocumentExporter,
    Localizer,
    SessionAudio,
    SessionRepository,
    TaskExporter,
    TranscriptSearch,
)
from vozata.settings_file import SettingsFile
from vozata.settings_options import OptionLists
from vozata.storage.audio_import import AudioFileImporter
from vozata.worker_client.discovery import FoundWorker
from vozata.worker_client.pairing import PairedWorker, pair_with_worker
from vozata.worker_client.status import WorkerStatus


class AskRunner(Protocol):
    def start(self, answer_id: str, question: str, session_id: str | None) -> bool:
        """Answer in the background (phase 24); False while another answer is streaming."""
        ...


class DeviceCatalog(Protocol):
    def inputs(self) -> list[DeviceInfo]: ...

    def loopbacks(self) -> list[DeviceInfo]: ...

    def default_input(self) -> DeviceInfo | None: ...

    def default_loopback(self) -> DeviceInfo | None: ...


class BackgroundJob(Protocol):
    """Runs on its own thread while the API serves (phase 54: the meeting detector)."""

    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class ApiContainer:
    settings: Settings  # as the engine started (keys that apply on restart)
    settings_file: SettingsFile  # current settings; `PUT /settings` updates them and `.env`
    localizer: Localizer
    labeler: SpeakerLabeler
    store: SessionRepository
    broadcaster: EventBroadcaster
    manager: SessionManager
    devices: DeviceCatalog
    gpu_info: Callable[[], GpuInfo]
    llm_reachable: Callable[[], bool]
    # (id, template) -> queued (phase 40: False when the meeting is already in the queue); then
    # `minutes_ready`
    regenerate_minutes: Callable[[str, str | None], bool]
    release_models: Callable[[], None] = lambda: None  # at shutdown (kept Whisper, phase 26)
    # at shutdown, first (phase 40): cancel the queue's running step and stop its worker
    stop_processing: Callable[[], None] = lambda: None
    exporters: Mapping[str, DocumentExporter] = field(default_factory=dict)  # by format (11)
    search_index: TranscriptSearch | None = None  # `GET /search` (22); None: no hits
    templates: TemplateRepository = field(default_factory=bundled_templates)  # minutes (20)
    vocabulary_file: Callable[[], Path] = lambda: Path("vocabulary.txt")  # glossary (19)
    voice_commands_file: Callable[[], Path] = lambda: Path("voice_commands.json")  # (50)
    ask: AskRunner | None = None  # `POST /ask` (24); None: 503 ask_unavailable
    # Minutes of part of a meeting (48); None: 503 partial_minutes_unavailable
    partial_minutes: PartialMinutesJob | None = None
    # The request history of each meeting (59); None: requests are not recorded
    requests: RequestLog | None = None
    # Action items (23): background extraction (then `action_items_ready`; None: 503), the
    # configured export targets, and an exporter per target (None when not configured).
    extract_action_items: Callable[[str], bool] | None = None  # False: already queued (40)
    task_targets: Callable[[], list[str]] = list
    task_exporter: Callable[[str], TaskExporter | None] = lambda target: None
    # The storage backend (31): `GET /health` and the `storage` field of a session.
    storage: StorageInfo = StorageInfo(StorageBackend.FILES.value)
    # The sessions' audio (32): `GET /sessions/{id}/audio/{track}`, dropped by
    # `DELETE /sessions/{id}`; None: no audio. `audio_cache`: the WAVs built from the database
    # (`GET /health`, `DELETE /storage/cache`, 38); None: no cache (file backend).
    audio: SessionAudio | None = None
    audio_cache: AudioCache | None = None
    # The import of the session folders recorded before phase 31 (33): `GET /migration` and the
    # first WebSocket messages; None: nothing to import (file backend).
    migration: MigrationJob | None = None
    # Meeting app detection (54): polls while the API serves; None: off (not Windows).
    meeting_detector: BackgroundJob | None = None
    # Meeting ZIPs (39): `POST /sessions/import`; None: 503 import_unavailable.
    bundle_importer: BundleImporter | None = None
    # Audio files recorded elsewhere (60): `POST /sessions/import-audio`; None: 503.
    audio_importer: AudioFileImporter | None = None
    # Config page (38): `GET /settings/options` lists and `POST /settings/test/{target}` checks.
    setting_options: Callable[[], OptionLists] = lambda: OptionLists({}, {})
    connection_check: Callable[[CheckTarget, Settings], CheckResult] = lambda target, settings: (
        CheckResult(False, "unavailable")
    )
    # Model downloads (42): the running ones are sent to a newly connected WebSocket client.
    downloads: DownloadTracker = field(default_factory=lambda: DownloadTracker(lambda state: None))
    # The VozAta worker (44): `GET /health` asks it with the current `WORKER_URL` / `WORKER_TOKEN`.
    worker_status: Callable[[Settings], WorkerStatus] = lambda settings: WorkerStatus(False)
    # Phase 47: the workers that answer a broadcast, and pairing by the code shown on the worker
    discover_workers: Callable[[Settings], list[FoundWorker]] = lambda settings: []
    pair_worker: Callable[[str, str], PairedWorker] = pair_with_worker
