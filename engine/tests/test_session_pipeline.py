from __future__ import annotations

import numpy as np
import pytest

from tests.fakes import FakeSessionObserver, FakeTranscriber
from vozata.session_pipeline import _DeferredTranscriber


def test_the_deferred_transcriber_refuses_work_before_the_model_is_loaded() -> None:
    deferred = _DeferredTranscriber(FakeTranscriber, FakeSessionObserver(), lambda error: None)

    with pytest.raises(RuntimeError, match="not loaded"):
        deferred.transcribe(np.zeros(4, np.float32), "en")


def test_the_deferred_transcriber_delegates_once_loaded_and_leaves_closing_to_the_session() -> None:
    observer = FakeSessionObserver()
    fake = FakeTranscriber()
    deferred = _DeferredTranscriber(lambda: fake, observer, lambda error: None)

    assert deferred.load()
    deferred.transcribe(np.ones(4, np.float32), "pt", "hint")
    deferred.close()

    assert deferred.loaded is fake
    assert [(language, hints) for _, language, hints in fake.calls] == [("pt", "hint")]
    assert not fake.closed
    assert observer.of("model_loading") == [(True,), (False,)]
