"""`wav_stream` (phase 32): range parsing and byte-exact WAV streaming."""

from __future__ import annotations

import pytest

from vozata.api.wav_stream import RangeNotSatisfiableError, byte_range, wav_bytes


class _Track:
    """A stereo track whose frame i holds the samples (i, -i)."""

    rate = 3
    channels = 2

    def __init__(self, frames: int, readable: int | None = None) -> None:
        self.frames = frames
        self._readable = frames if readable is None else readable

    def read(self, start: int, count: int) -> bytes:
        end = min(start + count, self._readable)
        return b"".join(
            i.to_bytes(2, "little", signed=True) + (-i).to_bytes(2, "little", signed=True)
            for i in range(start, end)
        )


def test_no_header_means_the_whole_file() -> None:
    assert byte_range(None, 10) is None


def test_an_empty_file_has_no_last_bytes() -> None:
    with pytest.raises(RangeNotSatisfiableError):
        byte_range("bytes=-5", 0)


@pytest.mark.parametrize(("first", "last"), [(0, 0), (43, 46), (45, 61), (50, 50), (0, 83)])
def test_any_byte_range_matches_the_whole_stream(first: int, last: int) -> None:
    track = _Track(10)
    whole = b"".join(wav_bytes(track))

    assert len(whole) == 44 + 10 * 4
    assert b"".join(wav_bytes(track, first, last)) == whole[first : last + 1]


def test_a_track_that_shrank_ends_the_stream_early() -> None:
    track = _Track(10, readable=4)

    body = b"".join(wav_bytes(track))

    assert len(body) == 44 + 4 * 4
