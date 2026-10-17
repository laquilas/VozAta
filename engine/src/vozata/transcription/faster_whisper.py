"""faster-whisper `Transcriber`: GPU with CPU fallback (thin; covered by a manual GPU smoke run)."""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np

from vozata.config import Settings
from vozata.domain import TranscriptionResult, WhisperDevice, Word
from vozata.transcription.cuda import register_cuda_dlls

_log = logging.getLogger(__name__)

ModelFactory = Callable[..., Any]
HALLUCINATION_SILENCE_SECONDS = 2.0  # skip silent stretches where Whisper tends to invent text


def _whisper_model(size: str, device: str, compute_type: str) -> Any:  # pragma: no cover - GPU
    from faster_whisper import WhisperModel

    return WhisperModel(size, device=device, compute_type=compute_type)


class FasterWhisperTranscriber:
    """Whisper on CUDA (`WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE`) or CPU (`WHISPER_CPU_MODEL`).

    `WHISPER_DEVICE=auto` loads the GPU model and runs a 1 s warm-up probe, because missing CUDA
    DLLs only fail at the first transcription; any failure falls back to the CPU model.
    """

    def __init__(self, settings: Settings, model_factory: ModelFactory | None = None) -> None:
        register_cuda_dlls()
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # the xet download protocol hangs here
        factory = model_factory or _whisper_model
        self.device, self._model = self._load(settings, factory)

    @staticmethod
    def _load(settings: Settings, factory: ModelFactory) -> tuple[str, Any]:
        if settings.whisper_device is not WhisperDevice.CPU:
            try:
                model = factory(
                    settings.whisper_model,
                    device="cuda",
                    compute_type=settings.whisper_compute_type,
                )
                segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en")
                list(segments)  # the probe only runs when the generator is consumed
                return "cuda", model
            except Exception as error:
                if settings.whisper_device is WhisperDevice.CUDA:
                    raise
                _log.warning(
                    "GPU unavailable (%s); using CPU model %s", error, settings.whisper_cpu_model
                )
        return "cpu", factory(settings.whisper_cpu_model, device="cpu", compute_type="int8")

    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        if self._model is None:
            raise RuntimeError("FasterWhisperTranscriber is closed")
        segments, info = self._model.transcribe(
            samples,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
            beam_size=1,
            hotwords=_text(hints),
            initial_prompt=_text(prompt),
            hallucination_silence_threshold=HALLUCINATION_SILENCE_SECONDS,
        )
        segments = list(segments)
        words = tuple(
            Word(word.word, word.start, word.end, min(1.0, max(0.0, word.probability)))
            for segment in segments
            for word in segment.words or ()
        )
        logprobs = [segment.avg_logprob for segment in segments]
        return TranscriptionResult(
            words=words,
            language=info.language,
            avg_logprob=sum(logprobs) / len(logprobs) if logprobs else None,
        )

    def close(self) -> None:
        """Release the model (frees VRAM before diarization or the LLM run)."""
        self._model = None
        gc.collect()


def _text(value: str | None) -> str | None:
    return value if value and value.strip() else None
