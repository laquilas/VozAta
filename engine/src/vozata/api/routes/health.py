"""`GET /health`: engine, GPU, speech-to-text and language-model status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata import __version__
from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import GpuStatus, Health, LlmStatus, SttStatus
from vozata.config import Settings
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
