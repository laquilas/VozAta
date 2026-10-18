"""`SqliteAudioStore` reading (phase 32): chunk ranges, the mix on read, WAVs in the cache."""

from __future__ import annotations

import os
import wave
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.audio.wav_writer import to_pcm16
from vozata.domain import AudioTrack, Channel
from vozata.ports import AudioMixer
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

RATE = 100  # small chunks (100 samples) keep the arithmetic readable
MIC_IN = (np.arange(350) * 50 / 32767).astype(np.float32)
SYSTEM_IN = (-np.arange(230) * 120 / 32767).astype(np.float32)
MIC = to_pcm16(MIC_IN)  # what is stored
SYSTEM = to_pcm16(SYSTEM_IN)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "vozata.db")
    yield database
    database.close()


def _recorded(
    database: Database, tmp_path: Path, mixer: AudioMixer, limit: int = 1 << 30
) -> tuple[SqliteAudioStore, str]:
    store = SqliteAudioStore(database, RATE, mixer, WavCache(tmp_path / "cache", limit), 3600)
    session_id = SqliteSessionRepository(database, tmp_path / "recordings").create(
        datetime(2026, 10, 15, 20, 23, 58)
    )
    for channel, samples in ((Channel.MIC, MIC_IN), (Channel.SYSTEM, SYSTEM_IN)):
        writer = store.open_writer(session_id, channel)
        writer.write(samples, 0.0)
        writer.finalize(0)  # different lengths on purpose: the mix pads the shorter one
    return store, session_id


@pytest.fixture
def recorded(database: Database, tmp_path: Path) -> tuple[SqliteAudioStore, str]:
    return _recorded(database, tmp_path, MonoMixer())


@pytest.mark.parametrize(
    ("start", "count"),
    [(0, 10), (95, 10), (100, 100), (150, 250), (340, 100), (0, 1000), (-5, 10)],
)
def test_frames_read_any_range_across_chunks(
    recorded: tuple[SqliteAudioStore, str], start: int, count: int
) -> None:
    store, session_id = recorded

    frames = store.frames(session_id, Channel.MIC, start, count)

    first = max(start, 0)
    assert frames.dtype == np.int16
    assert frames.tolist() == MIC[first : first + count].tolist()


def test_frames_past_the_end_or_empty_are_empty(recorded: tuple[SqliteAudioStore, str]) -> None:
    store, session_id = recorded

    assert store.frames(session_id, Channel.MIC, 350, 10).tolist() == []
    assert store.frames(session_id, Channel.MIC, 10, 0).tolist() == []
    assert store.frames("20990101_000000", Channel.MIC, 0, 10).tolist() == []
    assert store.length("20990101_000000", Channel.MIC) == 0


def test_lengths_and_rate(recorded: tuple[SqliteAudioStore, str]) -> None:
    store, session_id = recorded

    assert store.length(session_id, Channel.MIC) == 350
    assert store.length(session_id, Channel.SYSTEM) == 230
    assert store.sample_rate(session_id, Channel.SYSTEM) == RATE


@pytest.mark.parametrize("mixer", [MonoMixer(block_seconds=1), StereoMixer(block_seconds=1)])
def test_the_mix_on_read_equals_the_mixer_output(
    database: Database, tmp_path: Path, mixer: AudioMixer
) -> None:
    store, session_id = _recorded(database, tmp_path, mixer)
    mixer.mix(store, session_id, tmp_path / "mixed.wav")  # what the WAV backend writes
    with wave.open(str(tmp_path / "mixed.wav"), "rb") as wav:
        expected = wav.readframes(wav.getnframes())
        channels = wav.getnchannels()

    mixed = store.track(session_id, AudioTrack.MIXED)

    assert (mixed.channels, mixed.frames) == (channels, 350)
    assert b"".join(mixed.read(start, 70) for start in range(0, 350, 70)) == expected
    assert store.materialize_wav(session_id, AudioTrack.MIXED).read_bytes()[44:] == expected


def test_a_materialized_wav_is_reused_while_it_matches(
    recorded: tuple[SqliteAudioStore, str],
) -> None:
    store, session_id = recorded
    path = store.materialize_wav(session_id, Channel.MIC)
    assert path == store.cache.root / session_id / "mic.wav"
    with wave.open(str(path), "rb") as wav:
        assert wav.getnframes() == 350
        assert np.frombuffer(wav.readframes(350), "<i2").tolist() == MIC.tolist()
    os.utime(path, (1, 1))
    path.write_bytes(path.read_bytes())  # same size: reused (touched, not rebuilt)
    os.utime(path, (1, 1))

    assert store.materialize_wav(session_id, Channel.MIC) == path
    assert path.stat().st_mtime > 1

    path.write_bytes(b"RIFF")  # a stale file is rebuilt
    assert store.materialize_wav(session_id, Channel.MIC).stat().st_size == 44 + 700


def test_the_least_recently_used_wavs_are_evicted(database: Database, tmp_path: Path) -> None:
    store, session_id = _recorded(database, tmp_path, MonoMixer(), limit=1200)
    mic = store.materialize_wav(session_id, Channel.MIC)  # 744 bytes
    os.utime(mic, (1, 1))

    system = store.materialize_wav(session_id, Channel.SYSTEM)  # 504 bytes: over the limit

    assert system.exists()
    assert not mic.exists()
    assert store.cache.size() == 504


def test_an_empty_track_materializes_as_an_empty_wav(database: Database, tmp_path: Path) -> None:
    store = SqliteAudioStore(database, RATE, MonoMixer(), WavCache(tmp_path / "cache", 1 << 20))
    session_id = SqliteSessionRepository(database, tmp_path / "recordings").create(
        datetime(2026, 10, 15, 20, 23, 58)
    )

    assert store.track(session_id, AudioTrack.MIXED) is None
    with wave.open(str(store.materialize_wav(session_id, Channel.SYSTEM)), "rb") as wav:
        assert wav.getnframes() == 0
