"""Everything the API routes depend on, built by `bootstrap.build_api_container` (tests: fakes)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vozata.api.session_manager import SessionManager
from vozata.api.system_info import GpuInfo
from vozata.api.ws import EventBroadcaster
from vozata.audio.devices import DeviceInfo
from vozata.config import Settings
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer
from vozata.storage.session_store import SessionStore


class DeviceCatalog(Protocol):
    def inputs(self) -> list[DeviceInfo]: ...

    def loopbacks(self) -> list[DeviceInfo]: ...

    def default_input(self) -> DeviceInfo | None: ...

    def default_loopback(self) -> DeviceInfo | None: ...


@dataclass(frozen=True)
class ApiContainer:
    settings: Settings
    localizer: Localizer
    labeler: SpeakerLabeler
    store: SessionStore
    broadcaster: EventBroadcaster
    manager: SessionManager
    devices: DeviceCatalog
    gpu_info: Callable[[], GpuInfo]
    llm_reachable: Callable[[], bool]
    regenerate_minutes: Callable[[str], None]  # runs in the background, then `minutes_ready`
    release_models: Callable[[], None] = lambda: None  # at shutdown (kept Whisper, phase 26)
