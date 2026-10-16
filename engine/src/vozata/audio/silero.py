"""`SpeechDetector` over the Silero VAD model bundled with faster-whisper (CPU, ONNX)."""

from __future__ import annotations

import numpy as np
from faster_whisper import vad

RAW_MIN_SILENCE_MS = 100  # split spans at short gaps; `VadChunker` applies VAD_MIN_SILENCE_MS


class SileroSpeechDetector:
    """Unpadded speech spans: padding, pause length and blips are the chunker's policy.

    The model is loaded once per process (`get_vad_model` is cached) and is stateless per call,
    so one instance can serve several channels.
    """

    def __init__(self, sample_rate: int, threshold: float) -> None:
        self._rate = sample_rate
        self._options = vad.VadOptions(
            threshold=threshold,
            min_speech_duration_ms=0,
            min_silence_duration_ms=RAW_MIN_SILENCE_MS,
            speech_pad_ms=0,
        )

    def speech_spans(self, samples: np.ndarray) -> list[tuple[float, float]]:
        spans = vad.get_speech_timestamps(samples, self._options, sampling_rate=self._rate)
        return [(span["start"] / self._rate, span["end"] / self._rate) for span in spans]
