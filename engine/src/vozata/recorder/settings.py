"""The recorder's settings, read from the engine's `.env` without importing `vozata.config`.

`vozata.config` validates every engine key and pulls in more than the recorder may load; the
recorder needs only a few keys, read the same way (the process environment over `.env` in the
working directory, blank = not set). A bad value falls back to the default: the recorder must
always start.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

_log = logging.getLogger(__name__)

KEYS = (
    "OUTPUT_DIR",
    "SAMPLE_RATE",
    "AUTOSAVE_SECONDS",
    "RECORDER_PORT",
    "RECORDER_FSYNC_SECONDS",
    "RECORDER_MAX_SEGMENT_MB",
    "RECORDER_BUFFER_WARN_SECONDS",
)


@dataclass(frozen=True)
class RecorderSettings:
    output_dir: Path = Path("recordings")
    sample_rate: int = 16000
    autosave_seconds: float = 10.0
    port: int = 8766
    fsync_seconds: float = 2.0
    max_segment_mb: int = 2000
    buffer_warn_seconds: float = 30.0
    open_timeout: float = 20.0  # a WASAPI open can hang in the driver

    @property
    def max_segment_bytes(self) -> int:
        return self.max_segment_mb * 1024 * 1024


def load_recorder_settings(
    env: Mapping[str, str] | None = None, env_file: Path | None = None
) -> RecorderSettings:
    """Settings from `env` (default: the process environment over `.env` here)."""
    if env is None:
        env = os.environ
        env_file = env_file or Path(".env")
    merged: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        merged.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    merged.update({key: env[key] for key in KEYS if key in env})
    raw = {key: merged[key].strip() for key in KEYS if (merged.get(key) or "").strip()}
    return RecorderSettings(
        output_dir=Path(raw.get("OUTPUT_DIR", "recordings")),
        sample_rate=int(_number(raw, "SAMPLE_RATE", 16000, 8000, 48000)),
        autosave_seconds=_number(raw, "AUTOSAVE_SECONDS", 10.0, 1, 300),
        port=int(_number(raw, "RECORDER_PORT", 8766, 1024, 65535)),
        fsync_seconds=_number(raw, "RECORDER_FSYNC_SECONDS", 2.0, 0.5, 30),
        max_segment_mb=int(_number(raw, "RECORDER_MAX_SEGMENT_MB", 2000, 100, 3900)),
        buffer_warn_seconds=_number(raw, "RECORDER_BUFFER_WARN_SECONDS", 30.0, 5, 3600),
    )


def _number(raw: Mapping[str, str], key: str, default: float, low: float, high: float) -> float:
    if key not in raw:
        return default
    try:
        value = float(raw[key])
    except ValueError:
        _log.warning("%s=%r is not a number; using %s", key, raw[key], default)
        return default
    if not low <= value <= high:
        _log.warning("%s=%s is outside %s-%s; using %s", key, value, low, high, default)
        return default
    return value
