"""The pyannote model repos (phase 42): light, so the engine can pre-download them without
importing the child-side modules that load torch."""

from __future__ import annotations

DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"  # bundles its sub-models
EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"  # live speaker embeddings (15)


def short_name(repo_id: str) -> str:
    """The model as shown in the download bar: the repo name without its owner."""
    return repo_id.rsplit("/", 1)[-1]
