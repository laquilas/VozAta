"""`WavCache` (phase 32): atomic writes, reuse, LRU eviction under the size limit."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioReader
from vozata.audio.pcm import ChannelTrack
from vozata.domain import Channel
from vozata.storage.audio_cache import WavCache


def _track(frames: int) -> ChannelTrack:
    reader = FakeAudioReader({Channel.MIC: np.ones(frames, np.int16)})
    return ChannelTrack(reader, "s", Channel.MIC)


def test_size_of_a_missing_cache_is_zero_and_clean_does_nothing(tmp_path: Path) -> None:
    cache = WavCache(tmp_path / "cache", 100)

    cache.clean()

    assert cache.size() == 0
    assert not cache.root.exists()


def test_clean_evicts_oldest_first_and_removes_leftovers_and_empty_folders(
    tmp_path: Path,
) -> None:
    cache = WavCache(tmp_path / "cache", 1 << 20)
    old = cache.wav("a", "mic", _track(100))  # 244 bytes
    new = cache.wav("b", "mic", _track(100))
    os.utime(old, (1, 1))
    leftover = cache.root / "b" / ".mic-123.tmp"
    leftover.write_bytes(b"x")
    (cache.root / "empty").mkdir()

    WavCache(cache.root, 300).clean()

    assert not old.exists()
    assert new.exists()
    assert not leftover.exists()
    assert not (cache.root / "a").exists()
    assert not (cache.root / "empty").exists()


def test_a_file_in_use_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = WavCache(tmp_path / "cache", 1 << 20)
    busy = cache.wav("a", "mic", _track(100))

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", refuse)
    WavCache(cache.root, 0).clean()

    assert busy.exists()


def test_a_failed_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    cache = WavCache(tmp_path / "cache", 1 << 20)

    class Broken:
        rate, channels, frames = 100, 1, 10

        def read(self, start: int, count: int) -> bytes:
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        cache.wav("a", "mic", Broken())

    assert list((cache.root / "a").iterdir()) == []


def test_drop_removes_a_session(tmp_path: Path) -> None:
    cache = WavCache(tmp_path / "cache", 1 << 20)
    cache.wav("a", "mic", _track(10))

    cache.drop("a")
    cache.drop("missing")

    assert not (cache.root / "a").exists()


def test_the_file_just_built_is_kept_even_over_the_limit(tmp_path: Path) -> None:
    cache = WavCache(tmp_path / "cache", 0)

    path = cache.wav("a", "mic", _track(10))

    assert path.exists()
