from __future__ import annotations

import base64
import io
import json

import numpy as np

from tests.fakes import FakeEmbedder
from vozata.diarization.embed_child import PREFIX, main
from vozata.diarization.embedder import PyannoteEmbedder
from vozata.domain import WhisperDevice

REQUEST = json.dumps({"hf_token": "hf_x", "device": "cpu", "sample_rate": 16000}) + "\n"


def _clip(values: list[float]) -> str:
    data = np.asarray(values, dtype="<f4").tobytes()
    return json.dumps({"samples": base64.b64encode(data).decode("ascii")}) + "\n"


def _replies(out: io.StringIO) -> list[dict]:
    lines = out.getvalue().splitlines()
    assert all(line.startswith(PREFIX) for line in lines)
    return [json.loads(line[len(PREFIX) :]) for line in lines]


def test_loads_once_then_answers_every_clip_and_closes_at_eof() -> None:
    embedder = FakeEmbedder([[1, 2], [3, 4]])
    built: list[tuple] = []

    def build(token: str, device: WhisperDevice, rate: int) -> FakeEmbedder:
        built.append((token, device, rate))
        return embedder

    out = io.StringIO()
    stdin = io.StringIO(REQUEST + _clip([0.5, -0.5]) + "\n" + _clip([1.0]))

    assert main(stdin, out, build) == 0

    assert built == [("hf_x", WhisperDevice.CPU, 16000)]
    assert _replies(out) == [{"ready": True}, {"embedding": [1, 2]}, {"embedding": [3, 4]}]
    assert embedder.calls[0].tolist() == [0.5, -0.5]
    assert embedder.closed


def test_a_bad_clip_answers_an_error_and_the_child_goes_on() -> None:
    embedder = FakeEmbedder([[7]])
    out = io.StringIO()
    stdin = io.StringIO(REQUEST + "{not json\n" + _clip([1.0]))

    assert main(stdin, out, lambda *args: embedder) == 0

    replies = _replies(out)
    assert replies[0] == {"ready": True}
    assert replies[1]["error"].startswith("JSONDecodeError")
    assert replies[2] == {"embedding": [7]}


def test_a_failed_load_answers_the_error_and_exits_1() -> None:
    def build(*args: object) -> FakeEmbedder:
        raise RuntimeError("no extra")

    out = io.StringIO()

    assert main(io.StringIO(REQUEST), out, build) == 1
    assert _replies(out) == [{"error": "RuntimeError: no extra"}]


def test_the_pyannote_embedder_refuses_clips_before_loading_and_closes_quietly() -> None:
    embedder = PyannoteEmbedder("hf_x")

    embedder.close()  # nothing loaded: nothing to release
    assert embedder._inference is None
