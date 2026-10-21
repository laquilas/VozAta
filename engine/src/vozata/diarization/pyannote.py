"""pyannote.audio speaker diarization (optional extra `diarization`).

`torch` and `pyannote.audio` are imported only when the pipeline loads, so the engine works without
the extra. The engine runs this class in a child process (`diarization.child`), never next to
faster-whisper: both ship their own CUDA / cuDNN libraries, and the process exit frees the VRAM.
"""

from __future__ import annotations

import wave
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from vozata.diarization.models import DIARIZATION_MODEL as MODEL
from vozata.domain import SpeakerTurn, WhisperDevice
from vozata.ports import DiarizationError


def turns_from_tracks(tracks: Iterable[tuple[float, float, str]]) -> list[SpeakerTurn]:
    """`(start, end, label)` tracks as turns in time order; labels numbered by first turn."""
    ordered = sorted(tracks, key=lambda track: (track[0], track[1]))
    indexes: dict[str, int] = {}
    turns = []
    for start, end, label in ordered:
        if end <= start:
            continue
        index = indexes.setdefault(label, len(indexes))
        turns.append(SpeakerTurn(round(start, 3), round(end, 3), index))
    return turns


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Mono 16-bit PCM as float32 in [-1, 1] and its sample rate (the session WAV format)."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise DiarizationError(f"{path.name} is not mono 16-bit PCM")
        frames = wav.readframes(wav.getnframes())
        rate = wav.getframerate()
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0, rate


class PyannoteDiarizer:
    """Runs the pyannote speaker-diarization pipeline on a session WAV."""

    def __init__(self, hf_token: str, device: WhisperDevice = WhisperDevice.AUTO) -> None:
        self._token = hf_token
        self._device = device
        self._pipeline: Any = None

    def diarize(  # pragma: no cover - needs the extra, a token and (ideally) a GPU
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        samples, rate = read_wav(wav)  # before any download: a bad file fails fast
        try:
            import torch
        except ImportError as error:
            raise DiarizationError(
                'the diarization extra is not installed (pip install -e ".[diarization]")'
            ) from error
        pipeline = self._load(torch)
        audio = {"waveform": torch.from_numpy(samples)[None, :], "sample_rate": rate}
        hints = {
            key: value
            for key, value in (("min_speakers", min_speakers), ("max_speakers", max_speakers))
            if value is not None
        }
        result = pipeline(audio, **hints)
        # the overlap-free annotation: one speaker at a time suits transcript alignment
        annotation = getattr(result, "exclusive_speaker_diarization", None) or getattr(
            result, "speaker_diarization", result
        )
        return turns_from_tracks(
            (segment.start, segment.end, str(label))
            for segment, _, label in annotation.itertracks(yield_label=True)
        )

    def _load(self, torch: Any) -> Any:  # pragma: no cover - needs the extra and a token
        if self._pipeline is not None:
            return self._pipeline
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(MODEL, token=self._token)  # pyannote.audio >= 4
        if pipeline is None:
            raise DiarizationError(f"{MODEL} could not be loaded: accept its terms on Hugging Face")
        use_cuda = self._device is WhisperDevice.CUDA or (
            self._device is WhisperDevice.AUTO and torch.cuda.is_available()
        )
        pipeline.to(torch.device("cuda" if use_cuda else "cpu"))
        self._pipeline = pipeline
        return pipeline

    def close(self) -> None:
        if self._pipeline is None:
            return
        self._pipeline = None  # pragma: no cover - only after a real run
        import torch  # pragma: no cover

        if torch.cuda.is_available():  # pragma: no cover
            torch.cuda.empty_cache()
