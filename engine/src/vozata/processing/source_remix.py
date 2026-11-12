"""Rebuild a meeting's `mic` / `system` tracks from other kept sources (phase 66).

The same gain-sharing mix as the recorder's (phase 65), over a fixed choice of sources, written
over the stored channels; the meeting is then transcribed again by its usual job.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from vozata.audio.wav_writer import to_pcm16
from vozata.domain import Channel
from vozata.ports import PcmImport
from vozata.recorder.source_mix import FRAME_SECONDS, automix
from vozata.storage.source_archive import SourceArchive

CHUNK_SECONDS = 30.0


class UnknownSourceError(ValueError):
    """A chosen source is not kept for this meeting."""


def remix(
    archive: SourceArchive,
    audio: PcmImport,
    session_id: str,
    selected: set[str],
    sample_rate: int,
) -> dict[Channel, int]:
    """Write the mix of `selected` into both channels (silence for a kind with none); returns
    the frames written per channel. `UnknownSourceError` for an id the meeting does not keep."""
    sources = archive.list(session_id)
    known = {source.source_id for source in sources}
    unknown = selected - known
    if unknown:
        raise UnknownSourceError(", ".join(sorted(unknown)))
    length = max((source.frames for source in sources), default=0)
    chunk = max(1, round(CHUNK_SECONDS * sample_rate))
    frame = max(1, round(FRAME_SECONDS * sample_rate))
    written: dict[Channel, int] = {}
    for kind in (Channel.MIC, Channel.SYSTEM):
        ids = [s.source_id for s in sources if s.kind == kind and s.source_id in selected]
        written[kind] = audio.import_pcm(
            session_id, kind, _blocks(archive, session_id, ids, length, chunk, frame)
        )
    archive.set_selected(session_id, selected)
    return written


def _blocks(
    archive: SourceArchive,
    session_id: str,
    ids: list[str],
    length: int,
    chunk: int,
    frame: int,
) -> Iterator[bytes]:
    for start in range(0, length, chunk):
        count = min(chunk, length - start)
        parts = []
        for source_id in ids:
            samples = archive.frames(session_id, source_id, start, count).astype(np.float32)
            padded = np.zeros(count, np.float32)
            padded[: len(samples)] = samples / 32767.0
            parts.append(padded)
        mixed = automix(parts, frame) if parts else np.zeros(count, np.float32)
        yield to_pcm16(mixed).tobytes()
