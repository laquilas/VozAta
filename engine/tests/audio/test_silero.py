from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from faster_whisper import vad

from vozata.audio.silero import SileroSpeechDetector
from vozata.ports import SpeechDetector

SPEECH = Path(__file__).parent.parent / "data" / "speech_en.wav"
RATE = 16000


def _speech() -> np.ndarray:
    with wave.open(str(SPEECH), "rb") as wav:
        assert wav.getframerate() == RATE and wav.getnchannels() == 1
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768


def test_satisfies_the_speech_detector_port() -> None:
    assert isinstance(SileroSpeechDetector(RATE, 0.5), SpeechDetector)


def test_silence_has_no_speech() -> None:
    assert SileroSpeechDetector(RATE, 0.5).speech_spans(np.zeros(2 * RATE, np.float32)) == []


def test_finds_the_speech_in_a_recording_padded_with_silence() -> None:
    speech = _speech()
    silence = np.zeros(RATE, dtype=np.float32)

    spans = SileroSpeechDetector(RATE, 0.5).speech_spans(np.concatenate((silence, speech, silence)))

    assert spans
    duration = len(speech) / RATE
    assert spans[0][0] >= 0.9  # the leading second is silence
    assert spans[-1][1] <= 1.0 + duration + 0.1
    assert all(start < end for start, end in spans)


def test_asks_for_raw_spans_with_the_configured_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[vad.VadOptions] = []

    def fake(audio: np.ndarray, options: vad.VadOptions, sampling_rate: int) -> list[dict]:
        seen.append(options)
        assert sampling_rate == RATE
        return [{"start": 1600, "end": 8000}, {"start": 16000, "end": 24000}]

    monkeypatch.setattr(vad, "get_speech_timestamps", fake)

    spans = SileroSpeechDetector(RATE, 0.65).speech_spans(np.zeros(2 * RATE, np.float32))

    assert spans == [(0.1, 0.5), (1.0, 1.5)]
    options = seen[0]
    assert (options.threshold, options.speech_pad_ms, options.min_speech_duration_ms) == (
        0.65,
        0,
        0,
    )
    assert options.min_silence_duration_ms == 100
