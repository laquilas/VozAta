"""Repair the transcript a crash cut short (phase 17); WAVs are repaired by `wav_repair`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from vozata.domain import TranscriptSegment

_log = logging.getLogger(__name__)


def repair_transcript(path: Path) -> int:
    """Keep the readable lines of `transcript.jsonl`; move the others to `<name>.damaged`.

    A crash can cut the last line in half. Returns how many lines were moved (0: untouched).
    """
    if not path.is_file():
        return 0
    text = path.read_bytes().decode("utf-8", errors="replace")
    good: list[str] = []
    damaged: list[str] = []
    for line in text.splitlines():
        if line.strip():
            (good if _readable(line) else damaged).append(line)
    if not damaged:
        return 0
    side = path.with_name(path.name + ".damaged")
    with side.open("a", encoding="utf-8", newline="\n") as file:
        file.write("".join(line + "\n" for line in damaged))
    path.write_text("".join(line + "\n" for line in good), encoding="utf-8", newline="\n")
    _log.warning("Moved %d damaged line(s) of %s to %s", len(damaged), path, side.name)
    return len(damaged)


def _readable(line: str) -> bool:
    try:
        TranscriptSegment.from_dict(json.loads(line))
    except (ValueError, KeyError, TypeError):
        return False
    return True
