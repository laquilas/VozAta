"""`session.json` content of a recording session (architecture §8, schema_version 1)."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Protocol

from vozata.config import Settings
from vozata.domain import Channel, ConversationLanguage, SessionStatus
from vozata.session_title import stored_title

SCHEMA_VERSION = 1


class MetaStore(Protocol):
    def read_meta(self, session_id: str) -> dict[str, Any]: ...

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None: ...


class DeviceNames(Protocol):
    @property
    def device_names(self) -> Any: ...

    @property
    def minutes_template(self) -> str: ...

    @property
    def vocabulary(self) -> tuple[str, ...]: ...

    @property
    def title(self) -> str | None: ...


class SessionMeta:
    """Thread-safe metadata, saved on every change (language may be detected on another thread).

    The conversation language is written only when known: a fixed language at start, or the
    language `auto` mode detected. Once capture ended (`capture_ended`) the session no longer owns
    `session.json` alone (a rename, the processing job): every later change is merged into the
    stored metadata instead of rewriting it from memory.
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
        self._merge = False
        names = components.device_names
        self._meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": session_id,
            "status": SessionStatus.RECORDING.value,
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": None,
            "app_language": settings.app_language.value,
            "template": components.minutes_template,
            "vocabulary": list(components.vocabulary),
            "devices": {channel.value: names[channel] for channel in Channel if channel in names},
            "pauses": [],
            "settings": {
                "CHUNK_MODE": settings.chunk_mode.value,
                "CHUNK_SECONDS": settings.chunk_seconds,
                "WHISPER_MODEL": settings.whisper_model,
                "MIX_MODE": settings.mix_mode.value,
            },
        }
        if components.title is not None:
            self._meta["title"] = components.title  # phase 35; absent = untitled

    @classmethod
    def restore(cls, store: MetaStore, session_id: str, meta: dict[str, Any]) -> SessionMeta:
        """Continue an existing `session.json` (crash recovery, phase 17)."""
        restored = cls.__new__(cls)
        restored._store = store
        restored._id = session_id
        restored._lock = threading.Lock()
        restored._merge = False
        restored._meta = dict(meta)
        return restored

    def set_language(self, language: ConversationLanguage, source: str) -> None:
        if language is ConversationLanguage.AUTO:
            return
        self._update(language=language.value, language_source=source)

    @property
    def title(self) -> str | None:
        """The meeting title (phase 35); None when untitled."""
        with self._lock:
            return stored_title(self._meta)

    def set_title(self, title: str | None) -> None:
        """Rename the meeting (normalized title; None clears it), also while recording."""
        self._update(title=title)

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

    def capture_ended(self, at: datetime, duration_seconds: float) -> None:
        """Capture stopped (phase 40): the recorded length and `capture_ended_at`, which tells a
        restarted engine the meeting only waits for its processing."""
        self._update(
            duration_seconds=round(duration_seconds, 3),
            capture_ended_at=at.isoformat(timespec="seconds"),
        )
        with self._lock:
            self._merge = True

    def echo_dropped(self, count: int) -> None:
        """Mic segments the echo filter dropped (phase 18), written once the transcript is final."""
        self._update(echo_dropped=count)

    def heartbeat(self, at: datetime, duration_seconds: float) -> None:
        """Autosave every `AUTOSAVE_SECONDS` (phase 17): proof of life and the length so far."""
        self._update(
            last_heartbeat_at=at.isoformat(timespec="seconds"),
            duration_seconds=round(duration_seconds, 3),
        )

    def ended(self, at: datetime) -> None:
        self._update(ended_at=at.isoformat(timespec="seconds"))

    def _update(self, **fields: Any) -> None:
        with self._lock:
            if self._merge:
                self._meta = self._store.read_meta(self._id)
            self._meta.update(fields)
            self._save()

    def _save(self) -> None:
        self._store.write_meta(self._id, self._meta)
