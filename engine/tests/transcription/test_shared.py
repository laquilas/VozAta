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
    second.transcribe(np.ones(4, np.float32), "pt", "Avalonia", "Bom dia.")

    assert isinstance(first, Transcriber)
    assert len(loader.models) == 1
    assert not loader.models[0].closed
    assert loader.models[0].calls[0][2] == "Avalonia"
    assert loader.models[0].prompts == ["Bom dia."]
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

    shared.lease(keep=True).close()
    shared.release()
    shared.release()

    assert [model.closed for model in loader.models] == [True]
    assert not shared.loaded


def test_a_lease_closing_while_another_is_open_does_not_close_the_model() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)
    queue_step = shared.lease(keep=False)  # minutes follow: it asks for the unload
    live = shared.lease(keep=True)  # a live session that timed out the gate

    queue_step.close()
    live.transcribe(np.ones(4, np.float32), "pt")

    assert len(loader.models) == 1 and not loader.models[0].closed
    live.close()  # the last open lease: the asked-for unload happens now
    assert loader.models[0].closed
    assert not shared.loaded


def test_a_direct_release_waits_for_the_open_lease() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)
    live = shared.lease(keep=True)

    shared.release()  # e.g. "Regenerate minutes" while a recording uses Whisper
    live.transcribe(np.ones(4, np.float32), "pt")

    assert not loader.models[0].closed
    live.close()
    assert loader.models[0].closed and not shared.loaded


def test_closing_a_lease_twice_counts_once() -> None:
    loader = Loader()
    shared = SharedTranscriber(loader)
    first = shared.lease(keep=False)
    second = shared.lease(keep=True)

    first.close()
    first.close()

    assert not loader.models[0].closed  # `second` is still open
    second.close()
    assert loader.models[0].closed
