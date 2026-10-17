"""Child process that runs a diarizer: `python -m vozata.diarization.child` (phase 14).

The request comes as JSON on stdin (so the Hugging Face token never shows in a process list):
`{"wav", "output", "hf_token", "device", "min_speakers", "max_speakers"}`. The turns are written
to `output` as `{"turns": [[start, end, speaker_index], ...]}`; on failure the reason goes to
stderr and the exit code is 1. Libraries may print to stdout, so it is not used for the result.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from vozata.domain import WhisperDevice
from vozata.ports import Diarizer

DiarizerBuilder = Callable[[str, WhisperDevice], Diarizer]


def _pyannote(hf_token: str, device: WhisperDevice) -> Diarizer:  # pragma: no cover - extra
    from vozata.diarization.pyannote import PyannoteDiarizer

    return PyannoteDiarizer(hf_token, device)


def main(
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    build: DiarizerBuilder = _pyannote,
) -> int:
    err = stderr or sys.stderr
    try:
        request = json.loads((stdin or sys.stdin).read())
        diarizer = build(str(request["hf_token"]), WhisperDevice(request["device"]))
        try:
            turns = diarizer.diarize(
                Path(request["wav"]), request.get("min_speakers"), request.get("max_speakers")
            )
        finally:
            diarizer.close()
        rows: Sequence[list[float]] = [[t.start, t.end, t.speaker_index] for t in turns]
        Path(request["output"]).write_text(json.dumps({"turns": rows}), encoding="utf-8")
    except Exception as error:
        err.write(f"{type(error).__name__}: {error}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
