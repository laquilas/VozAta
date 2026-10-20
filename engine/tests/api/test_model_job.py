from __future__ import annotations

import pytest

from tests.fakes import FakeLanguageModel
from vozata.api.model_job import Cancels
from vozata.processing.cancel import CancelToken


class _Stuck(FakeLanguageModel):
    def close(self) -> None:
        raise RuntimeError("socket stuck")


def test_close_unhooks_the_token_and_closes_every_watched_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = CancelToken()
    cancels = Cancels(token)
    stuck, other = cancels.watch(_Stuck()), cancels.watch(FakeLanguageModel())

    cancels.close()
    cancels.close()  # idempotent
    token.cancel()

    assert (stuck.cancels, other.cancels) == (0, 0)  # no longer tied to the token
    assert other.closes == 1
    assert "Closing a language model client failed" in caplog.text
