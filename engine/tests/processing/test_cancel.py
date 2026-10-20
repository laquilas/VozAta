import pytest

from vozata.processing.cancel import CancelToken, StepCancelled


def test_cancel_runs_callbacks_once_and_late_callbacks_immediately():
    token = CancelToken()
    calls: list[str] = []
    token.on_cancel(lambda: calls.append("a"))
    assert token.cancelled is False

    token.cancel()
    token.cancel()
    assert token.cancelled is True
    assert calls == ["a"]

    token.on_cancel(lambda: calls.append("b"))
    assert calls == ["a", "b"]


def test_unregistered_callback_is_not_called():
    token = CancelToken()
    calls: list[str] = []
    unregister = token.on_cancel(lambda: calls.append("a"))
    unregister()
    unregister()
    token.cancel()
    assert calls == []


def test_raise_if_cancelled():
    token = CancelToken()
    token.raise_if_cancelled()
    token.cancel()
    with pytest.raises(StepCancelled):
        token.raise_if_cancelled()


def test_callbacks_run_outside_the_lock():
    token = CancelToken()
    seen: list[bool] = []
    token.on_cancel(lambda: seen.append(token.cancelled))
    token.on_cancel(lambda: token.on_cancel(lambda: seen.append(True)))
    token.cancel()
    assert seen == [True, True]
