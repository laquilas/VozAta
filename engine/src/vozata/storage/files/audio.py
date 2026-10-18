"""`FileAudioStore`: a session's audio as `mic.wav`, `system.wav` and `mixed.wav` (architecture §8).

Implements `AudioStore`, `AudioReader` and `AudioTracks` (`SessionAudio`) and `RecoverableStore`
for the WAVs.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from vozata.audio.wav_writer import AlignedWavWriter
from vozata.domain import AudioTrack, Channel
from vozata.ports import AudioMixer, AudioTrackWriter, PcmTrack, StoreRepairError
from vozata.storage.session_store import SessionStore
from vozata.storage.wav_repair import WavRepairError, pad_wav, repair_wav


class FileAudioStore:
    """One mono 16-bit WAV per channel in the session folder; the mix goes to `mixed.wav`."""

    def __init__(self, store: SessionStore, sample_rate: int) -> None:
        self._store = store
        self._rate = sample_rate

    def open_writer(self, session_id: str, channel: Channel) -> AudioTrackWriter:
        return AlignedWavWriter(self._wav(session_id, channel), self._rate)

    def write_mix(self, session_id: str, mixer: AudioMixer) -> None:
        mixer.mix(self, session_id, self._store.paths(session_id).mixed_wav)

    def frames(self, session_id: str, channel: Channel, start: int, count: int) -> np.ndarray:
        with self._open(session_id, channel) as wav:
            wav.setpos(min(max(start, 0), wav.getnframes()))
            return np.frombuffer(wav.readframes(max(count, 0)), dtype=np.int16)

    def length(self, session_id: str, channel: Channel) -> int:
        with self._open(session_id, channel) as wav:
            return wav.getnframes()

    def sample_rate(self, session_id: str, channel: Channel) -> int:
        with self._open(session_id, channel) as wav:
            return wav.getframerate()

    def materialize_wav(self, session_id: str, channel: Channel | AudioTrack) -> Path:
        """The recorded WAV itself (`mixed.wav` for the mix): nothing to build."""
        return self._store.paths(session_id).root / f"{AudioTrack(channel).value}.wav"

    def track(self, session_id: str, track: AudioTrack) -> PcmTrack | None:
        """`mic.wav`, `system.wav` or `mixed.wav` (written by `write_mix`); None when missing."""
        path = self.materialize_wav(session_id, track)
        return WavFileTrack(path) if path.is_file() else None

    def repair(self, session_id: str) -> float | None:
        """Repair both WAV headers and pad the tracks to the longest one (phase 17).

        Returns the recorded length in seconds; raises `StoreRepairError`.
        """
        wavs = [self._wav(session_id, channel) for channel in Channel]
        try:
            frames = max(repair_wav(wav, self._rate) for wav in wavs)
            for wav in wavs:
                pad_wav(wav, frames)
        except (WavRepairError, OSError) as error:
            raise StoreRepairError(str(error)) from error
        return round(frames / self._rate, 3)

    def _wav(self, session_id: str, channel: Channel) -> Path:
        return self._store.paths(session_id).wav(channel)

    def _open(self, session_id: str, channel: Channel) -> wave.Wave_read:
        path = self._wav(session_id, channel)
        wav = wave.open(str(path), "rb")  # noqa: SIM115 (returned to a `with` block)
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            wav.close()
            raise ValueError(f"{path} must be mono 16-bit PCM")
        return wav


class WavFileTrack:
    """A 16-bit PCM WAV file as a `PcmTrack` (mono or stereo)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        with wave.open(str(path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise ValueError(f"{path} must be 16-bit PCM")
            self.rate = wav.getframerate()
            self.channels = wav.getnchannels()
            self.frames = wav.getnframes()

    def read(self, start: int, count: int) -> bytes:
        if start < 0 or count <= 0 or start >= self.frames:
            return b""
        with wave.open(str(self._path), "rb") as wav:
            wav.setpos(start)
            return wav.readframes(count)
