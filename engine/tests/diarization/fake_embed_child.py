"""A stand-in embedder child for `SubprocessEmbedder` tests: `python fake_embed_child.py <mode>`.

Modes: `ok` (the embedding is [mean, len]), `noise` (stray stdout lines first), `load_error`,
`crash` (exits on the first clip), `slow` (the first clip takes 1 s), `bad` (malformed reply).
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np

from vozata.diarization.embed_child import PREFIX, main
from vozata.domain import WhisperDevice


class _Embedder:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def embed(self, samples: np.ndarray) -> np.ndarray:
        if self.mode == "crash":
            sys.exit(3)
        if self.mode == "slow":
            time.sleep(1.0)
        if self.mode == "bad":
            sys.stdout.write(PREFIX + json.dumps({"embedding": "nope"}) + "\n")
            sys.stdout.flush()
            sys.exit(0)
        return np.array([float(samples.mean()), float(len(samples))])

    def close(self) -> None:
        pass


def _build(mode: str):
    def build(hf_token: str, device: WhisperDevice, sample_rate: int) -> _Embedder:
        if mode == "load_error":
            sys.stderr.write("\nloading failed\n")
            raise RuntimeError(f"bad token {hf_token[:2]}")
        if mode == "noise":
            sys.stdout.write("Downloading model...\n")
            sys.stdout.write(PREFIX + "not json\n")
            sys.stdout.write(PREFIX + "[1, 2]\n")
        return _Embedder(mode)

    return build


if __name__ == "__main__":
    sys.exit(main(build=_build(sys.argv[1])))
