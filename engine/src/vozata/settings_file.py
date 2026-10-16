"""The engine's current settings and `.env` updates from `PUT /settings` (phase 10)."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values, set_key

from vozata.config import KEYS, ConfigError, Settings, load_settings
from vozata.settings_fields import FIELDS
from vozata.settings_view import SECRET_MASK

FIELD_BY_KEY = {field.key: field for field in FIELDS}
SECRET_KEYS = frozenset(field.key for field in FIELDS if field.secret)
WRITE_ATTEMPTS = 5
WRITE_RETRY_SECONDS = 0.2  # sync tools such as OneDrive briefly lock a file they are uploading


class SettingsWriteError(OSError):
    """`.env` could not be written (still locked after retrying); `str()` holds the reason."""


class SettingsFile:
    """`current` settings plus validated, persisted updates.

    An update is validated as a whole with `config.load_settings` before anything is written; only
    keys whose parsed value changes are written, one by one with `dotenv.set_key`, so comments and
    order in `.env` are kept. Process environment variables keep overriding `.env`, as at start-up.
    """

    def __init__(
        self, path: Path, current: Settings, environ: Mapping[str, str] | None = None
    ) -> None:
        self._path = path
        self._current = current
        self._environ = os.environ if environ is None else environ
        self._lock = threading.Lock()

    @property
    def current(self) -> Settings:
        return self._current

    def update(self, values: Mapping[str, object]) -> list[str]:
        """Apply `values` (JSON values; `None` clears a key); returns the keys needing a restart.

        Raises `ConfigError` (unknown key or invalid value) without changing anything, and
        `SettingsWriteError` when `.env` stays locked (keys written before it may be saved).
        """
        with self._lock:
            requested: dict[str, str] = {}
            for key, value in values.items():
                if key not in FIELD_BY_KEY:
                    raise ConfigError(key, _text(value), "unknown_key")
                if key in SECRET_KEYS and value == SECRET_MASK:
                    continue  # the UI sends the mask back for an untouched secret
                requested[key] = _text(value)
            stored = self._stored()
            before = load_settings(env=stored)
            after = load_settings(env={**stored, **requested})
            changed = [
                key
                for key in requested
                if getattr(before, FIELD_BY_KEY[key].attribute)
                != getattr(after, FIELD_BY_KEY[key].attribute)
            ]
            overrides = {key: self._environ[key] for key in KEYS if self._environ.get(key)}
            current = load_settings(env={**stored, **requested, **overrides})
            self._write({key: requested[key] for key in changed})
            self._current = current
            return [key for key in changed if FIELD_BY_KEY[key].applies == "restart"]

    def _stored(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return {key: value or "" for key, value in dotenv_values(self._path).items() if key in KEYS}

    def _write(self, changes: Mapping[str, str]) -> None:
        if not changes:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()
        for key, text in changes.items():
            self._set(key, text)

    def _set(self, key: str, text: str) -> None:
        attempt = 1
        while True:
            try:
                set_key(self._path, key, text, quote_mode="never")
                return
            except PermissionError as error:
                if attempt >= WRITE_ATTEMPTS:
                    raise SettingsWriteError(str(error)) from error
                attempt += 1
                time.sleep(WRITE_RETRY_SECONDS)


def _text(value: object) -> str:
    """A JSON value as `.env` text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
