"""The speaker runtime (phase 56): where the packaged engine finds torch and pyannote.

The installer no longer bundles them. `vozata-engine speakers install` builds a separate Python
environment in `root` on the PC that needs speaker identification; the diarizer and the live
embedder children (phases 14 / 15) then start with its Python, with the engine's own source
(`<engine>/speakers/vozata.zip`) on `PYTHONPATH`. In development the children run with the
virtualenv's Python, as before.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from vozata.config import ConfigError, Settings

BUNDLE_FOLDER = "speakers"  # next to vozata-engine.exe: uv.exe and vozata.zip


@dataclass(frozen=True)
class ChildCommand:
    argv: list[str]
    env: Mapping[str, str] = field(default_factory=dict)  # added to the inherited environment


@dataclass(frozen=True)
class SpeakerRuntime:
    root: Path  # %LOCALAPPDATA%\VozAta\speakers
    bundle: Path | None  # <engine>\speakers in the packaged engine; None in development

    @property
    def packaged(self) -> bool:
        return self.bundle is not None

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def python(self) -> Path:
        return self.venv / "Scripts" / "python.exe"

    @property
    def marker(self) -> Path:
        return self.root / "ready.json"

    @property
    def uv(self) -> Path:
        return (self.bundle or self.root) / "uv.exe"

    @property
    def source_zip(self) -> Path:
        return (self.bundle or self.root) / "vozata.zip"

    def is_ready(self) -> bool:
        """Installed and checked: `ready.json` is written last, after the import check."""
        return self.marker.is_file() and self.python.is_file()

    def details(self) -> dict[str, object]:
        """What `ready.json` recorded (the torch variant, the versions); empty when unreadable."""
        try:
            value = json.loads(self.marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def child(self, module: str) -> ChildCommand:
        """How to start `python -m module` for a speaker child process. The packaged engine
        without the runtime cannot: a configuration error that says how to install it."""
        if not self.packaged:
            return ChildCommand([sys.executable, "-m", module])
        if not self.is_ready():
            raise ConfigError("DIARIZATION_PROVIDER", "pyannote", "speakers_not_installed")
        return ChildCommand(
            [str(self.python), "-m", module],
            {"PYTHONPATH": str(self.source_zip), "PYTHONNOUSERSITE": "1"},
        )


def bundle_dir(
    frozen: bool = bool(getattr(sys, "frozen", False)), executable: str = sys.executable
) -> Path | None:
    """`<engine>\\speakers` when running as the packaged engine, else None."""
    return Path(executable).parent / BUNDLE_FOLDER if frozen else None


def runtime_for(settings: Settings, bundle: Path | None = None) -> SpeakerRuntime:
    return SpeakerRuntime(settings.speakers_runtime_dir, bundle if bundle else bundle_dir())
