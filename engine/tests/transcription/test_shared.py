from __future__ import annotations

import numpy as np

from tests.fakes import FakeTranscriber
from vozata.ports import Transcriber
from vozata.transcription.shared import SharedTranscriber


class Loader:
    def __init__(self) -> None:
        self.models: list[FakeTranscriber] = []

    def __call__(self) -> FakeTranscriber:
        self.models.append(FakeTranscriber())
        return self.models[-1]


def test_leases_that_keep_the_model_reuse_one_load() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)

    first = shared.lease(keep=True)
    first.close()
    second = shared.lease(keep=True)
    second.transcribe(np.ones(4, np.float32), "pt")

    assert isinstance(first, Transcriber)
    assert len(loader.models) == 1
    assert not loader.models[0].closed
    assert len(loader.models[0].calls) == 1
    assert shared.loaded


def test_a_lease_without_keep_unloads_and_the_next_lease_reloads() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)

    shared.lease(keep=False).close()

    assert loader.models[0].closed
    assert not shared.loaded
    shared.lease(keep=True)
    assert len(loader.models) == 2


def test_release_unloads_once_and_is_safe_when_nothing_is_loaded() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)
    shared.release()

    shared.lease(keep=True)
    shared.release()
    shared.release()

    assert [model.closed for model in loader.models] == [True]
    assert not shared.loaded
