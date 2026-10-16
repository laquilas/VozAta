from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from vozata.config import Settings
from vozata.domain import WhisperDevice
from vozata.ports import Transcriber
from vozata.transcription.faster_whisper import FasterWhisperTranscriber


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class FakeSegment:
    words: list[FakeWord] | None


@dataclass
class FakeInfo:
    language: str


@dataclass
class FakeModel:
    size: str
    device: str
    compute_type: str
    segments: list[FakeSegment] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Any, FakeInfo]:
        self.calls.append(kwargs)
        return iter(self.segments), FakeInfo(language=kwargs.get("language") or "pt")


class Factory:
    def __init__(self, cuda_fails: bool = False) -> None:
        self.cuda_fails = cuda_fails
        self.models: list[FakeModel] = []

    def __call__(self, size: str, device: str, compute_type: str) -> FakeModel:
        if device == "cuda" and self.cuda_fails:
            raise RuntimeError("Library cublas64_12.dll is not found")
        model = FakeModel(size, device, compute_type)
        self.models.append(model)
        return model


def make(device: WhisperDevice, factory: Factory) -> FasterWhisperTranscriber:
    return FasterWhisperTranscriber(Settings(whisper_device=device), model_factory=factory)


def test_auto_uses_cuda_after_a_warm_up_probe() -> None:
    factory = Factory()

    transcriber = make(WhisperDevice.AUTO, factory)

    model = factory.models[0]
    assert (model.size, model.device, model.compute_type) == (
        "large-v3-turbo",
        "cuda",
        "int8_float16",
    )
    assert len(model.calls) == 1  # warm-up
    assert transcriber.device == "cuda"
    assert isinstance(transcriber, Transcriber)


def test_auto_falls_back_to_the_cpu_model(caplog: pytest.LogCaptureFixture) -> None:
    factory = Factory(cuda_fails=True)

    transcriber = make(WhisperDevice.AUTO, factory)

    model = factory.models[0]
    assert (model.size, model.device, model.compute_type) == ("small", "cpu", "int8")
    assert transcriber.device == "cpu"
    assert "cublas64_12.dll" in caplog.text


def test_explicit_cuda_does_not_fall_back() -> None:
    with pytest.raises(RuntimeError):
        make(WhisperDevice.CUDA, Factory(cuda_fails=True))


def test_explicit_cpu_skips_the_gpu() -> None:
    factory = Factory()

    assert make(WhisperDevice.CPU, factory).device == "cpu"
    assert [model.device for model in factory.models] == ["cpu"]


def test_transcribe_passes_streaming_options_and_maps_words() -> None:
    factory = Factory()
    transcriber = make(WhisperDevice.CPU, factory)
    model = factory.models[0]
    model.segments = [
        FakeSegment([FakeWord(" Olá", 0.1, 0.4, 0.97), FakeWord(" mundo.", 0.5, 0.9, 1.2)]),
        FakeSegment(None),
    ]

    result = transcriber.transcribe(np.zeros(16000, dtype=np.float32), "pt", hints="Avalonia")

    assert model.calls[-1] == {
        "language": "pt",
        "word_timestamps": True,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "beam_size": 1,
        "hotwords": "Avalonia",
    }
    assert [(w.text, w.start, w.end) for w in result.words] == [
        (" Olá", 0.1, 0.4),
        (" mundo.", 0.5, 0.9),
    ]
    assert result.words[1].probability == 1.0  # clamped to [0, 1]
    assert result.language == "pt"


def test_blank_hints_are_not_sent() -> None:
    factory = Factory()
    transcriber = make(WhisperDevice.CPU, factory)

    transcriber.transcribe(np.zeros(10, dtype=np.float32), None, hints="  ")

    assert factory.models[0].calls[-1]["hotwords"] is None


def test_close_releases_the_model() -> None:
    transcriber = make(WhisperDevice.CPU, Factory())

    transcriber.close()

    with pytest.raises(RuntimeError):
        transcriber.transcribe(np.zeros(10, dtype=np.float32), "en")
