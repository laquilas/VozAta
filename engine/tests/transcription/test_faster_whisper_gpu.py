"""Manual GPU smoke tests: `pytest -m gpu` (skipped by default).

Models come from this machine's configuration (`.env` / environment: `WHISPER_MODEL`,
`WHISPER_CPU_MODEL`); only the device is forced per test. Uncached models are downloaded.
"""

from __future__ import annotations

import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tests.transcription.contract import check_transcriber_contract
from vozata.config import Settings, load_settings
from vozata.domain import AudioChunk, Channel, WhisperDevice
from vozata.models.cli_progress import cli_downloader
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds

pytestmark = pytest.mark.gpu

SPEECH = Path(__file__).parent.parent / "data" / "speech_en.wav"


class FixedLanguage:
    def current(self) -> str | None:
        return "en"

    def observe(self, language: str | None, speech_seconds: float) -> None:
        pass


@pytest.fixture(scope="module")
def speech() -> np.ndarray:
    with wave.open(str(SPEECH), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate()) == (1, 16000)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16) / 32768.0


def _settings(**overrides: object) -> Settings:
    return replace(load_settings(), **overrides)


def _transcriber(settings: Settings) -> FasterWhisperTranscriber:
    return FasterWhisperTranscriber(settings, cli_downloader(settings))


def _words(text: str) -> list[str]:
    return [word.strip(".,").lower() for word in text.split()]


def test_gpu_transcriber_honours_the_contract(speech: np.ndarray) -> None:
    transcriber = _transcriber(_settings(whisper_device=WhisperDevice.CUDA))
    try:
        assert transcriber.device == "cuda"
        check_transcriber_contract(transcriber, speech.astype(np.float32), "en")
        text = "".join(
            w.text for w in transcriber.transcribe(speech.astype(np.float32), "en").words
        )
        assert {"beta", "friday", "release", "notes"} <= set(_words(text))
    finally:
        transcriber.close()


def test_cpu_fallback_model_honours_the_contract(speech: np.ndarray) -> None:
    transcriber = _transcriber(_settings(whisper_device=WhisperDevice.CPU))
    try:
        assert transcriber.device == "cpu"
        check_transcriber_contract(transcriber, speech.astype(np.float32), "en")
    finally:
        transcriber.close()


def test_stitched_windows_reproduce_the_speech_without_duplicates(speech: np.ndarray) -> None:
    settings = _settings(whisper_device=WhisperDevice.CUDA, chunk_seconds=2)
    transcriber = _transcriber(settings)
    stitcher = CarryOverStitcher(
        Channel.MIC, transcriber, settings, FixedLanguage(), SegmentIds().next
    )
    window = 2 * 16000
    samples = speech.astype(np.float32)
    try:
        segments = []
        for start in range(0, len(samples), window):
            chunk = AudioChunk(Channel.MIC, start / 16000, samples[start : start + window])
            segments += stitcher.on_chunk(chunk)
        segments += stitcher.flush()
    finally:
        transcriber.close()

    words = _words(" ".join(segment.text for segment in segments))
    expected = _words(
        "We will ship the beta on Friday. Please review the release notes before the meeting."
    )
    assert words == expected, words
    assert all(a.end <= b.start + 0.01 for a, b in zip(segments, segments[1:], strict=False))
