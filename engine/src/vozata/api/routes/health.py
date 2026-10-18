"""`GET /health`: engine, GPU, speech-to-text and language-model status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata import __version__
from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import GpuStatus, Health, LlmStatus, StorageStatus, SttStatus
from vozata.config import Settings
from vozata.storage.usage import database_size
from vozata.transcription.openai_compatible import remote_host

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health(c: Annotated[ApiContainer, Depends(container)]) -> Health:
    settings = c.settings  # speech-to-text keys apply on restart
    current = c.settings_file.current
    gpu = c.gpu_info()
    return Health(
        version=__version__,
        gpu=GpuStatus(available=gpu.available, name=gpu.name, vram_total_mb=gpu.vram_total_mb),
        stt=_stt(settings),
        llm=LlmStatus(
            provider=current.llm_provider,
            model=current.ollama_model,
            reachable=c.llm_reachable(),
        ),
        storage=_storage(c),
    )


def _storage(c: ApiContainer) -> StorageStatus:
    """The backend, the database path and size, the OneDrive warning (31), the size of the WAV
    cache (32, 38)."""
    info = c.storage
    database = str(info.database.resolve()) if info.database is not None else None
    warning = None
    if info.onedrive_root is not None:
        warning = c.localizer.t("storage.onedrive_warning", path=database, root=info.onedrive_root)
    return StorageStatus(
        backend=info.backend,
        database=database,
        warning=warning,
        size_bytes=database_size(info.database) if info.database is not None else None,
        audio_cache_bytes=c.audio_cache.size() if c.audio_cache is not None else 0,
    )


def _stt(settings: Settings) -> SttStatus:
    """Local Whisper reports its model and device; a remote API its model and host (privacy)."""
    host = remote_host(settings)
    if host is not None:
        return SttStatus(
            provider=settings.stt_provider, model=settings.openai_stt_model, device=host
        )
    return SttStatus(
        provider=settings.stt_provider,
        model=settings.whisper_model,
        device=settings.whisper_device.value,
    )
