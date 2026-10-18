"""A `PcmTrack` served as a WAV file over HTTP (phase 32): generated header, `Range` requests.

Only one range per request is supported (`bytes=a-b`, `bytes=a-`, `bytes=-n`); anything else,
or a range outside the file, is unsatisfiable (`416`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from vozata.audio.pcm import SAMPLE_WIDTH, WAV_HEADER_BYTES, wav_header, wav_size
from vozata.ports import PcmTrack

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
BLOCK_SECONDS = 1  # frames read from the store per step of the stream


class RangeNotSatisfiableError(ValueError):
    """The `Range` header names no bytes of the file."""


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The inclusive `(first, last)` byte range asked by `header`; None for the whole file.

    Raises `RangeNotSatisfiableError` for a malformed, multiple or out-of-file range.
    """
    if header is None:
        return None
    match = _RANGE.match(header.strip())
    if match is None or (not match[1] and not match[2]):
        raise RangeNotSatisfiableError(header)
    if not match[1]:  # the last n bytes
        suffix = int(match[2])
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(header)
        return max(size - suffix, 0), size - 1
    first = int(match[1])
    last = min(int(match[2]), size - 1) if match[2] else size - 1
    if first >= size or first > last:
        raise RangeNotSatisfiableError(header)
    return first, last


def wav_bytes(track: PcmTrack, first: int = 0, last: int | None = None) -> Iterator[bytes]:
    """Bytes `first`..`last` (inclusive) of `track` as a WAV file, read a block at a time."""
    size = wav_size(track)
    last = size - 1 if last is None else min(last, size - 1)
    if first < WAV_HEADER_BYTES:
        yield wav_header(track.rate, track.channels, track.frames)[first : last + 1]
    frame_bytes = track.channels * SAMPLE_WIDTH
    position = max(first, WAV_HEADER_BYTES)  # the next byte of the file to send
    block = max(1, track.rate * BLOCK_SECONDS)
    while position <= last:
        frame, skip = divmod(position - WAV_HEADER_BYTES, frame_bytes)
        wanted = last + 1 - position
        count = min(block, -(-(skip + wanted) // frame_bytes))
        data = track.read(frame, count)[skip : skip + wanted]
        if not data:  # the track is shorter than announced (it shrank): stop
            return
        yield data
        position += len(data)
