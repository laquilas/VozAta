"""Child process that embeds voice clips: `python -m vozata.diarization.embed_child` (phase 15).

A line protocol in UTF-8. The first stdin line is `{"hf_token", "device", "sample_rate"}` (so
the token never shows in a process list); the child loads the model and answers
`@vozata {"ready": true}`. Every next line `{"samples": "<base64 little-endian float32>"}` is
answered `@vozata {"embedding": [...]}`. Failures answer `@vozata {"error": "..."}`; a failed
load also ends the child with exit code 1. EOF on stdin ends it normally. Libraries may print to
stdout, so replies carry the `@vozata ` prefix and the parent ignores every other line.
"""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from typing import TextIO

import numpy as np

from vozata.domain import WhisperDevice
from vozata.ports import SpeakerEmbedder

PREFIX = "@vozata "
EmbedderBuilder = Callable[[str, WhisperDevice, int], SpeakerEmbedder]


def _pyannote(
    hf_token: str, device: WhisperDevice, sample_rate: int
) -> SpeakerEmbedder:  # pragma: no cover - needs the extra
    from vozata.diarization.embedder import PyannoteEmbedder

    embedder = PyannoteEmbedder(hf_token, device, sample_rate)
    embedder.load()
    return embedder


def main(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    build: EmbedderBuilder = _pyannote,
) -> int:
    source = stdin or sys.stdin
    out = stdout or sys.stdout

    def reply(**data: object) -> None:
        out.write(PREFIX + json.dumps(data) + "\n")
        out.flush()

    try:
        request = json.loads(source.readline())
        embedder = build(
            str(request["hf_token"]),
            WhisperDevice(request["device"]),
            int(request["sample_rate"]),
        )
    except Exception as error:
        reply(error=f"{type(error).__name__}: {error}")
        return 1
    try:
        reply(ready=True)
        for line in source:
            if not line.strip():
                continue
            try:
                data = base64.b64decode(json.loads(line)["samples"])
                vector = embedder.embed(np.frombuffer(data, dtype="<f4").astype(np.float32))
                reply(embedding=np.asarray(vector, dtype=np.float64).ravel().tolist())
            except Exception as error:
                reply(error=f"{type(error).__name__}: {error}")
    finally:
        embedder.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    replies = sys.stdout
    sys.stdout = sys.stderr  # stray library prints must not mix with the replies
    sys.exit(main(stdout=replies))
