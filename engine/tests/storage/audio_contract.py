"""Contract every `SessionAudio` (`AudioStore` + `AudioReader`) must honour (phase 30; reused by
the SQLite audio store in phase 32).

Subclass and provide `audio` (a store at `RATE` Hz) and `session_id` (an existing session):

    class TestSqliteAudio(AudioStoreContract):
        @pytest.fixture
        def audio(self, tmp_path: Path) -> SessionAudio: ...

        @pytest.fixture
        def session_id(self, audio: SessionAudio) -> str: ...
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioMixer
from vozata.domain import Channel
from vozata.ports import AudioReader, AudioTrackWriter, SessionAudio

RATE = 16000


def _record(audio: SessionAudio, session_id: str, blocks: dict[Channel, list[tuple]]) -> None:
    writers = {channel: audio.open_writer(session_id, channel) for channel in blocks}
    for channel, writes in blocks.items():
        for samples, at in writes:
            writers[channel].write(np.asarray(samples, dtype=np.float32), at)
    total = max(writer.samples_written for writer in writers.values()) / RATE
    for writer in writers.values():
        writer.finalize(total)


class AudioStoreContract:
    """Behaviour shared by every audio backend; subclasses provide `audio` and `session_id`."""

    @pytest.fixture
    def audio(self) -> SessionAudio:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    @pytest.fixture
    def session_id(self) -> str:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    def test_satisfies_the_ports(self, audio: SessionAudio, session_id: str) -> None:
        assert isinstance(audio, SessionAudio)
        assert isinstance(audio.open_writer(session_id, Channel.MIC), AudioTrackWriter)

    def test_written_samples_are_read_back_as_pcm16(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        _record(audio, session_id, {Channel.MIC: [([0.5, -0.5, 2.0, 0.0], 0.0)]})

        assert audio.sample_rate(session_id, Channel.MIC) == RATE
        assert audio.length(session_id, Channel.MIC) == 4
        assert audio.frames(session_id, Channel.MIC, 0, 10).tolist() == [16383, -16383, 32767, 0]
        assert audio.frames(session_id, Channel.MIC, 1, 2).tolist() == [-16383, 32767]
        assert audio.frames(session_id, Channel.MIC, 4, 2).tolist() == []

    def test_gaps_and_pauses_are_silence_and_tracks_end_equal(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        mic = audio.open_writer(session_id, Channel.MIC)
        system = audio.open_writer(session_id, Channel.SYSTEM)
        mic.write(np.full(RATE // 2, 0.5, np.float32), 0.0)
        system.write(np.full(RATE // 4, 0.5, np.float32), 0.5)  # nothing played before 0.5 s
        mic.paused = True
        mic.write(np.full(RATE // 2, 0.5, np.float32), 0.5)
        total = max(mic.samples_written, system.samples_written) / RATE
        mic.finalize(total)
        system.finalize(total)

        mic_frames = audio.frames(session_id, Channel.MIC, 0, RATE)
        system_frames = audio.frames(session_id, Channel.SYSTEM, 0, RATE)
        assert audio.length(session_id, Channel.MIC) == audio.length(session_id, Channel.SYSTEM)
        assert len(mic_frames) == len(system_frames) == RATE
        assert not mic_frames[RATE // 2 :].any()  # paused: silence
        assert not system_frames[: RATE // 2].any()  # the gap: silence
        assert system_frames[RATE // 2 : 3 * RATE // 4].all()

    def test_the_mix_reads_the_finished_tracks(self, audio: SessionAudio, session_id: str) -> None:
        _record(audio, session_id, {Channel.MIC: [([0.1], 0.0)], Channel.SYSTEM: [([0.2], 0.0)]})
        mixer = FakeAudioMixer()

        audio.write_mix(session_id, mixer)

        [(reader, mixed_id, _)] = mixer.calls
        assert isinstance(reader, AudioReader)
        assert mixed_id == session_id

    def test_a_track_can_be_materialized_as_a_wav_file(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        _record(audio, session_id, {Channel.SYSTEM: [([0.25] * 8, 0.0)]})

        path = audio.materialize_wav(session_id, Channel.SYSTEM)

        assert isinstance(path, Path)
        assert path.read_bytes()[:4] == b"RIFF"
