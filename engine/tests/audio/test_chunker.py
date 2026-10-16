from __future__ import annotations

import numpy as np
import pytest

from vozata.audio.chunker import FixedWindowChunker
from vozata.domain import AudioChunk, Channel

RATE = 10  # 1-second windows of 10 samples


@pytest.fixture
def chunks() -> list[AudioChunk]:
    return []


@pytest.fixture
def chunker(chunks: list[AudioChunk]) -> FixedWindowChunker:
    return FixedWindowChunker(Channel.MIC, 1.0, RATE, chunks.append, tolerance=0.15)


def _block(n: int, value: float = 1.0) -> np.ndarray:
    return np.full(n, value, dtype=np.float32)


def _starts(chunks: list[AudioChunk]) -> list[float]:
    return [chunk.start for chunk in chunks]


def test_emits_a_chunk_for_every_full_window(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    for i in range(5):
        chunker.feed(_block(5), at=i * 0.5)

    assert _starts(chunks) == [0.0, 1.0]
    assert all(len(chunk.samples) == 10 for chunk in chunks)
    assert all(chunk.channel is Channel.MIC for chunk in chunks)


def test_a_large_block_can_complete_several_windows(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(np.arange(25, dtype=np.float32), at=0.0)

    assert _starts(chunks) == [0.0, 1.0]
    assert chunks[1].samples[0] == 10.0


def test_gap_beyond_tolerance_is_filled_with_silence(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(_block(5), at=0.0)
    chunker.feed(_block(5), at=1.5)  # one second of loopback silence

    assert _starts(chunks) == [0.0, 1.0]
    assert chunks[0].samples.tolist() == [1.0] * 5 + [0.0] * 5
    assert chunks[1].samples.tolist() == [0.0] * 5 + [1.0] * 5


def test_first_block_arriving_late_keeps_windows_on_the_session_clock(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(_block(15), at=0.5)

    assert _starts(chunks) == [0.0, 1.0]
    assert not chunks[0].samples[:5].any()


def test_flush_emits_the_partial_window_once(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(_block(13), at=0.0)
    chunker.flush()
    chunker.flush()

    assert _starts(chunks) == [0.0, 1.0]
    assert len(chunks[1].samples) == 3


def test_pause_flushes_drops_audio_and_resume_restarts_windows(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(_block(4), at=0.0)
    chunker.paused = True
    chunker.feed(_block(20, 0.5), at=0.4)  # dropped
    chunker.paused = False
    chunker.feed(_block(10), at=2.4)

    assert _starts(chunks) == [0.0, 2.4]
    assert len(chunks[0].samples) == 4
    assert chunks[1].samples.tolist() == [1.0] * 10


def test_setting_pause_twice_does_not_emit_twice(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    chunker.feed(_block(4), at=0.0)
    chunker.paused = True
    chunker.paused = True

    assert len(chunks) == 1
    assert chunker.paused


def test_buffered_returns_a_copy_of_the_partial_window(
    chunker: FixedWindowChunker, chunks: list[AudioChunk]
) -> None:
    assert chunker.buffered() is None
    chunker.feed(_block(5), at=0.0)
    chunker.feed(_block(5), at=0.5)
    chunker.feed(_block(3, 0.5), at=1.0)

    buffered = chunker.buffered()

    assert buffered is not None
    assert (buffered.start, len(buffered.samples), buffered.channel) == (1.0, 3, Channel.MIC)
    buffered.samples[:] = 0
    chunker.flush()
    assert np.all(chunks[-1].samples == 0.5)
