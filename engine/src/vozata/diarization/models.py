"""The pyannote model repos (phase 42): light, so the engine can pre-download them without
importing the child-side modules that load torch."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vozata.diarization.runtime import SpeakerRuntime

DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"  # bundles its sub-models
EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"  # live speaker embeddings (15)


def has_extra(runtime: SpeakerRuntime | None = None) -> bool:
    """Is the `diarization` extra (torch and pyannote.audio) installed? The packaged engine
    has it once its speaker runtime is ready (phase 56). Nothing is imported: torch takes
    seconds to load (phase 51)."""
    if runtime is not None and runtime.packaged:
        return runtime.is_ready()
    try:
        return all(importlib.util.find_spec(name) for name in ("torch", "pyannote.audio"))
    except ModuleNotFoundError:  # `pyannote.audio` without its parent package
        return False


def short_name(repo_id: str) -> str:
    """The model as shown in the download bar: the repo name without its owner."""
    return repo_id.rsplit("/", 1)[-1]
