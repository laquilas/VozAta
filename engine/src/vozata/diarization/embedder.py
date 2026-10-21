"""pyannote speaker-embedding model (optional extra `diarization`, phase 15).

Runs only inside `diarization.embed_child`, never next to faster-whisper (each bundles its own
CUDA / cuDNN). `torch` and `pyannote.audio` are imported when the model loads. The model is small
(~30 MB), so it stays loaded for the whole recording next to Whisper.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from vozata.diarization.models import EMBEDDING_MODEL as MODEL
from vozata.domain import WhisperDevice
from vozata.ports import DiarizationError


class PyannoteEmbedder:
    """One embedding per clip (`window="whole"`)."""

    def __init__(
        self, hf_token: str, device: WhisperDevice = WhisperDevice.AUTO, sample_rate: int = 16000
    ) -> None:
        self._token = hf_token
        self._device = device
        self._rate = sample_rate
        self._torch: Any = None
        self._inference: Any = None

    def load(self) -> None:  # pragma: no cover - needs the extra and (ideally) a GPU
        """Load the model and run it once, so the first live clip is not slow."""
        try:
            import torch
            from pyannote.audio import Inference, Model
        except ImportError as error:
            raise DiarizationError(
                'the diarization extra is not installed (pip install -e ".[diarization]")'
            ) from error
        model = Model.from_pretrained(MODEL, token=self._token)
        if model is None:
            raise DiarizationError(f"{MODEL} could not be loaded: accept its terms on Hugging Face")
        use_cuda = self._device is WhisperDevice.CUDA or (
            self._device is WhisperDevice.AUTO and torch.cuda.is_available()
        )
        self._torch = torch
        self._inference = Inference(
            model, window="whole", device=torch.device("cuda" if use_cuda else "cpu")
        )
        self.embed(np.zeros(self._rate, dtype=np.float32))

    def embed(self, samples: np.ndarray) -> np.ndarray:  # pragma: no cover - needs the extra
        if self._inference is None:
            raise DiarizationError("the speaker embedding model is not loaded")
        waveform = self._torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
        vector = self._inference({"waveform": waveform[None, :], "sample_rate": self._rate})
        return np.asarray(vector, dtype=np.float32).ravel()

    def close(self) -> None:
        if self._inference is None:
            return
        self._inference = None  # pragma: no cover - only after a real load
        if self._torch.cuda.is_available():  # pragma: no cover
            self._torch.cuda.empty_cache()
