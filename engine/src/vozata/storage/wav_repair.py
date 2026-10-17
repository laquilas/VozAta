"""Repair the WAV headers a crash leaves stale and pad tracks to one length (phase 17).

A WAV being written has its RIFF and `data` sizes patched as frames arrive; if the process or the
machine dies, the sizes on disk can lag behind the samples actually written. The samples are all
there, so the sizes are recomputed from the file size. Nothing is ever cut from the file.
"""

from __future__ import annotations

import os
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_PCM = 1
_RIFF_HEADER = 12  # "RIFF" + size + "WAVE"
_CHUNK_HEADER = 8  # id + size
_SIZE = struct.Struct("<I")


class WavRepairError(ValueError):
    """The file is not a PCM WAV whose header can be repaired."""


@dataclass(frozen=True)
class _Layout:
    data_offset: int  # first byte of the samples
    block_align: int  # bytes per frame (all channels)


def repair_wav(path: Path, sample_rate: int) -> int:
    """Rewrite the RIFF and `data` sizes from the file size; return the number of frames.

    A missing or empty file (the crash came before any audio) becomes a valid, empty mono 16-bit
    WAV at `sample_rate`. A trailing partial frame is left in the file but not counted. Raises
    `WavRepairError` when the header itself is unreadable.
    """
    if not path.exists() or path.stat().st_size == 0:
        _write_empty(path, sample_rate)
        return 0
    with path.open("r+b") as file:
        layout = _read_layout(file, path)
        frames = _frames(file, layout)
        _write_sizes(file, layout, frames)
    return frames


def pad_wav(path: Path, frames: int) -> None:
    """Append silence until the (repaired) WAV holds `frames` frames; never shortens it."""
    with path.open("r+b") as file:
        layout = _read_layout(file, path)
        current = _frames(file, layout)
        if current >= frames:
            return
        file.seek(layout.data_offset + current * layout.block_align)
        missing = (frames - current) * layout.block_align
        block = 1 << 20
        while missing > 0:
            size = min(block, missing)
            file.write(bytes(size))
            missing -= size
        _write_sizes(file, layout, frames)


def wav_frames(path: Path) -> int:
    """Frames in a valid WAV, read from its header."""
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes()


def _write_empty(path: Path, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"")


def _frames(file: BinaryIO, layout: _Layout) -> int:
    size = file.seek(0, os.SEEK_END)
    return max(0, size - layout.data_offset) // layout.block_align


def _write_sizes(file: BinaryIO, layout: _Layout, frames: int) -> None:
    data_size = frames * layout.block_align
    file.seek(4)
    file.write(_SIZE.pack(layout.data_offset - _CHUNK_HEADER + data_size))
    file.seek(layout.data_offset - 4)
    file.write(_SIZE.pack(data_size))
    file.flush()
    os.fsync(file.fileno())


def _read_layout(file: BinaryIO, path: Path) -> _Layout:
    file.seek(0)
    head = file.read(_RIFF_HEADER)
    if len(head) < _RIFF_HEADER or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise WavRepairError(f"{path.name} has no RIFF/WAVE header")
    block_align = 0
    while True:
        chunk = file.read(_CHUNK_HEADER)
        if len(chunk) < _CHUNK_HEADER:
            raise WavRepairError(f"{path.name} has no data chunk")
        chunk_id, chunk_size = chunk[:4], _SIZE.unpack(chunk[4:])[0]
        if chunk_id == b"data":
            if block_align == 0:
                raise WavRepairError(f"{path.name} has no fmt chunk before its data")
            return _Layout(file.tell(), block_align)
        body = file.read(chunk_size + (chunk_size & 1))
        if chunk_id == b"fmt ":
            block_align = _block_align(body, path)


def _block_align(body: bytes, path: Path) -> int:
    if len(body) < 16:
        raise WavRepairError(f"{path.name} has a truncated fmt chunk")
    audio_format, channels, _rate, _byte_rate, block_align, _bits = struct.unpack(
        "<HHIIHH", body[:16]
    )
    if audio_format != _PCM or channels < 1 or block_align < 1:
        raise WavRepairError(f"{path.name} is not PCM audio")
    return block_align
