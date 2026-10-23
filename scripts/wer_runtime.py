"""The Whisper-bound part of `wer_benchmark.py` (phase 55): transcribe a WAV the way the engine
transcribes a stored meeting. Needs the models (and ideally the GPU): covered by the recorded
benchmark runs, not unit tests."""

from __future__ import annotations

import functools
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine" / "src"))

from vozata import bootstrap  # noqa: E402
from vozata.config import load_settings  # noqa: E402
from vozata.domain import Channel  # noqa: E402
from vozata.labels import SpeakerLabeler  # noqa: E402
from vozata.processing.cancel import CancelToken  # noqa: E402
from vozata.transcription.language_lock import LanguageLock  # noqa: E402
from vozata.transcription.offline import OfflineTranscription  # noqa: E402

SESSION = "benchmark"


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path} is not mono 16-bit PCM")
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16), wav.getframerate()


class _Audio:
    """The WAV as the mic track, silence as the system track (no echo, no second speaker)."""

    def __init__(self, samples: np.ndarray, rate: int) -> None:
        self._tracks = {Channel.MIC: samples, Channel.SYSTEM: np.zeros_like(samples)}
        self._rate = rate

    def frames(self, session_id: str, channel: Channel, start: int, count: int) -> np.ndarray:
        return self._tracks[channel][start : start + count]

    def length(self, session_id: str, channel: Channel) -> int:
        return len(self._tracks[channel])

    def sample_rate(self, session_id: str, channel: Channel) -> int:
        return self._rate

    def materialize_wav(self, session_id: str, channel: object) -> Path:
        raise NotImplementedError("the benchmark never diarizes")


class _Sink:
    def __init__(self) -> None:
        self.segments: list = []

    def emit(self, segment: object) -> None:
        self.segments.append(segment)

    def close(self) -> None:
        pass


class _Store:
    """A session with no transcript yet; what is transcribed stays in memory."""

    def __init__(self) -> None:
        self.sink = _Sink()

    def load_raw_transcript(self, session_id: str) -> list:
        return []

    def open_transcript(self, session_id: str, labeler: object) -> _Sink:
        return self.sink


def transcribe(audio: Path, overrides: dict[str, str]) -> tuple[str, float, float]:
    """The mic transcript of `audio` with these settings over this shell's environment (never a
    `.env`), the processing seconds and the audio seconds."""
    samples, rate = load_wav(audio)
    env = {**os.environ, **overrides, "ECHO_DEDUPE_ENABLED": "false", "SAMPLE_RATE": str(rate)}
    settings = load_settings(env=env)
    downloader = bootstrap.cli_downloader(settings, bootstrap.build_localizer(settings))
    store = _Store()
    offline = OfflineTranscription(
        settings,
        store,  # type: ignore[arg-type]
        _Audio(samples, rate),  # type: ignore[arg-type]
        lambda: bootstrap.build_transcriber(settings, downloader),
        SpeakerLabeler(bootstrap.build_localizer(settings)),
        LanguageLock(settings.transcription_language, lambda language: None),
        None,
        functools.partial(bootstrap.CHUNKERS[settings.chunk_mode], settings),
    )
    started = time.monotonic()
    offline.run(SESSION, CancelToken(), lambda fraction: None)
    seconds = time.monotonic() - started
    segments = sorted(
        (segment for segment in store.sink.segments if segment.channel is Channel.MIC),
        key=lambda segment: segment.start,
    )
    return " ".join(segment.text for segment in segments), seconds, len(samples) / rate
