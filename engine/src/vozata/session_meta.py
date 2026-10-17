"""`session.json` content of a recording session (architecture §8, schema_version 1)."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Protocol

from vozata.config import Settings
from vozata.domain import Channel, ConversationLanguage, SessionStatus

SCHEMA_VERSION = 1


class MetaStore(Protocol):
    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None: ...


class DeviceNames(Protocol):
    @property
    def device_names(self) -> Any: ...

    @property
    def minutes_template(self) -> str: ...


class SessionMeta:
    """Thread-safe metadata, saved on every change (language may be detected on another thread).

    The conversation language is written only when known: a fixed language at start, or the
    language `auto` mode detected.
    """

    def __init__(
        self,
        store: MetaStore,
        session_id: str,
        started_at: datetime,
        settings: Settings,
        components: DeviceNames,
    ) -> None:
        self._store = store
        self._id = session_id
        self._lock = threading.Lock()
        names = components.device_names
        self._meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": session_id,
            "status": SessionStatus.RECORDING.value,
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": None,
            "app_language": settings.app_language.value,
            "template": components.minutes_template,
            "devices": {channel.value: names[channel] for channel in Channel if channel in names},
            "pauses": [],
            "settings": {
                "CHUNK_MODE": settings.chunk_mode.value,
                "CHUNK_SECONDS": settings.chunk_seconds,
                "WHISPER_MODEL": settings.whisper_model,
                "MIX_MODE": settings.mix_mode.value,
            },
        }

    def set_language(self, language: ConversationLanguage, source: str) -> None:
        if language is ConversationLanguage.AUTO:
            return
        self._update(language=language.value, language_source=source)

    def set_status(self, status: SessionStatus) -> None:
        self._update(status=status.value)

    def pause_started(self, at: float) -> None:
        with self._lock:
            self._meta["pauses"].append({"start": at, "end": None})
            self._save()

    def pause_ended(self, at: float) -> None:
        """Close the pause opened by the last `pause_started`."""
        with self._lock:
            self._meta["pauses"][-1]["end"] = at
            self._save()

    def captured(self, duration_seconds: float) -> None:
        """Recorded length (session time when capture stopped), pauses included."""
        self._update(duration_seconds=round(duration_seconds, 3))

    def echo_dropped(self, count: int) -> None:
        """Mic segments the echo filter dropped (phase 18), written once the transcript is final."""
        self._update(echo_dropped=count)

    def ended(self, at: datetime) -> None:
        self._update(ended_at=at.isoformat(timespec="seconds"))

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self._meta.update(fields)
            self._save()

    def _save(self) -> None:
        self._store.write_meta(self._id, self._meta)
