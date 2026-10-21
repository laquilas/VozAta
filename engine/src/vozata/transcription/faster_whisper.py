"""faster-whisper `Transcriber`: GPU with CPU fallback (thin; covered by a manual GPU smoke run)."""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np

from vozata.config import Settings
from vozata.domain import ModelKind, TranscriptionResult, WhisperDevice, Word
from vozata.ports import ModelDownloader
from vozata.transcription.cuda import register_cuda_dlls

_log = logging.getLogger(__name__)

ModelFactory = Callable[..., Any]
HALLUCINATION_SILENCE_SECONDS = 2.0  # skip silent stretches where Whisper tends to invent text
# The files faster-whisper 1.2.1 downloads (`faster_whisper.utils.download_model`)
WHISPER_FILES = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)


def whisper_repo(name: str) -> str:
    """The Hugging Face repo of a `WHISPER_MODEL` value, resolved as faster-whisper 1.2.1 does:
    a name with `/` is a repo id, otherwise a size of `faster_whisper.utils._MODELS`."""
    if "/" in name:
        return name
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(name)
    if repo is None:
        raise ValueError(f"Invalid model size '{name}', expected one of: {', '.join(_MODELS)}")
    return repo


def model_folder(name: str, downloader: ModelDownloader) -> str:
    """An existing folder as is; otherwise the model's cached snapshot, downloaded with progress
    events when missing (phase 42)."""
    if os.path.isdir(name):
        return name
    repo = whisper_repo(name)
    return str(downloader.ensure(ModelKind.SPEECH, repo, allow_patterns=WHISPER_FILES, name=name))


def _whisper_model(path: str, device: str, compute_type: str) -> Any:  # pragma: no cover - GPU
    from faster_whisper import WhisperModel

    return WhisperModel(path, device=device, compute_type=compute_type)


class FasterWhisperTranscriber:
    """Whisper on CUDA (`WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE`) or CPU (`WHISPER_CPU_MODEL`).

    `WHISPER_DEVICE=auto` loads the GPU model and runs a 1 s warm-up probe, because missing CUDA
    DLLs only fail at the first transcription; any failure falls back to the CPU model. Each
    model is first made local through `downloader` (phase 42), then loaded from its folder.
    """

    def __init__(
        self,
        settings: Settings,
        downloader: ModelDownloader,
        model_factory: ModelFactory | None = None,
    ) -> None:
        register_cuda_dlls()
        factory = model_factory or _whisper_model
        self.device, self._model = self._load(settings, downloader, factory)

    @staticmethod
    def _load(
        settings: Settings, downloader: ModelDownloader, factory: ModelFactory
    ) -> tuple[str, Any]:
        if settings.whisper_device is not WhisperDevice.CPU:
            try:
                model = factory(
                    model_folder(settings.whisper_model, downloader),
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
        cpu_model = model_folder(settings.whisper_cpu_model, downloader)
        return "cpu", factory(cpu_model, device="cpu", compute_type="int8")

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
