"""Transcript sinks: console, `transcript.jsonl`, `transcript.md`, and fan-out."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from vozata.domain import TranscriptSegment
from vozata.formatting import render_line
from vozata.labels import SpeakerLabeler
from vozata.ports import TranscriptSink

_log = logging.getLogger(__name__)


class ConsoleSink:
    """Live `[hh:mm:ss] Label: text` lines on a terminal stream (left open on close)."""

    def __init__(self, labeler: SpeakerLabeler, stream: TextIO | None = None) -> None:
        self._labeler = labeler
        self._stream = stream or sys.stdout

    def emit(self, segment: TranscriptSegment) -> None:
        self._stream.write(render_line(segment, self._labeler.label(segment.speaker_id)) + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.flush()


class _AppendFile:
    def __init__(self, path: Path) -> None:
        self._file = path.open("a", encoding="utf-8", newline="\n")

    def _write_line(self, line: str) -> None:
        self._file.write(line + "\n")
        self._file.flush()  # every segment is on disk before the next one (crash safety)

    def close(self) -> None:
        self._file.close()


class JsonlSink(_AppendFile):
    """Raw, append-only `transcript.jsonl` (architecture §8)."""

    def emit(self, segment: TranscriptSegment) -> None:
        self._write_line(json.dumps(segment.to_dict(), ensure_ascii=False))


class MarkdownSink(_AppendFile):
    """Human-readable `transcript.md`."""

    def __init__(self, path: Path, labeler: SpeakerLabeler) -> None:
        super().__init__(path)
        self._labeler = labeler

    def emit(self, segment: TranscriptSegment) -> None:
        self._write_line(render_line(segment, self._labeler.label(segment.speaker_id)))


class CompositeSink:
    """Fan a segment out to every sink; a failing sink is logged and the others continue."""

    def __init__(self, sinks: Sequence[TranscriptSink]) -> None:
        self._sinks = list(sinks)

    def emit(self, segment: TranscriptSegment) -> None:
        for sink in self._sinks:
            try:
                sink.emit(segment)
            except Exception:
                _log.exception("Transcript sink %s failed to emit", type(sink).__name__)

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:
                _log.exception("Transcript sink %s failed to close", type(sink).__name__)
