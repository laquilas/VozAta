"""Everything the API routes depend on, built by `bootstrap.build_api_container` (tests: fakes)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from vozata.api.session_manager import SessionManager
from vozata.api.system_info import GpuInfo
from vozata.api.ws import EventBroadcaster
from vozata.audio.devices import DeviceInfo
from vozata.config import Settings
from vozata.domain import StorageBackend, StorageInfo
from vozata.labels import SpeakerLabeler
from vozata.minutes.template_repository import TemplateRepository, bundled_templates
from vozata.ports import (
    DocumentExporter,
    Localizer,
    SessionRepository,
    TaskExporter,
    TranscriptSearch,
)
from vozata.settings_file import SettingsFile


class AskRunner(Protocol):
    def start(self, answer_id: str, question: str, session_id: str | None) -> bool:
        """Answer in the background (phase 24); False while another answer is streaming."""
        ...


class DeviceCatalog(Protocol):
    def inputs(self) -> list[DeviceInfo]: ...

    def loopbacks(self) -> list[DeviceInfo]: ...

    def default_input(self) -> DeviceInfo | None: ...

    def default_loopback(self) -> DeviceInfo | None: ...


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
    regenerate_minutes: Callable[[str, str | None], None]  # (id, template); then `minutes_ready`
    release_models: Callable[[], None] = lambda: None  # at shutdown (kept Whisper, phase 26)
    exporters: Mapping[str, DocumentExporter] = field(default_factory=dict)  # by format (11)
    search_index: TranscriptSearch | None = None  # `GET /search` (22); None: no hits
    templates: TemplateRepository = field(default_factory=bundled_templates)  # minutes (20)
    vocabulary_file: Callable[[], Path] = lambda: Path("vocabulary.txt")  # glossary (19)
    ask: AskRunner | None = None  # `POST /ask` (24); None: 503 ask_unavailable
    # Action items (23): background extraction (then `action_items_ready`; None: 503), the
    # configured export targets, and an exporter per target (None when not configured).
    extract_action_items: Callable[[str], None] | None = None
    task_targets: Callable[[], list[str]] = list
    task_exporter: Callable[[str], TaskExporter | None] = lambda target: None
    # The storage backend (31): `GET /health` and the `storage` field of a session.
    storage: StorageInfo = StorageInfo(StorageBackend.FILES.value)
