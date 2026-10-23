"""The `LanguageModel` contract every provider must meet (phase 53).

A provider's test module defines a `harness` fixture returning a `Harness` and imports the
tests: `from tests.llm.contract import *  # noqa: F403`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from vozata.ports import Cancellable, LanguageModel, LanguageModelError, LlmUnreachableError

__all__ = [
    "Harness",
    "test_contract_satisfies_the_port",
    "test_contract_generate_returns_the_reply",
    "test_contract_stream_yields_the_reply_in_pieces",
    "test_contract_a_server_that_does_not_answer_is_unreachable",
    "test_contract_a_failing_server_is_a_language_model_error",
    "test_contract_release_and_close_never_fail_after_a_reply",
    "test_contract_cancel_makes_the_next_call_fail",
]

REPLY = "## Summary\nThe beta ships on Tuesday."


@dataclass(frozen=True)
class Harness:
    """How a provider is built for the contract tests."""

    replying: Callable[[str], LanguageModel]  # every call answers this text
    unreachable: Callable[[], LanguageModel]  # the server does not answer at all
    failing: Callable[[], LanguageModel]  # the server answers with an HTTP / API error


def test_contract_satisfies_the_port(harness: Harness) -> None:
    model = harness.replying(REPLY)

    assert isinstance(model, LanguageModel)
    assert isinstance(model, Cancellable)


def test_contract_generate_returns_the_reply(harness: Harness) -> None:
    assert harness.replying(REPLY).generate("be precise", "transcript") == REPLY


def test_contract_stream_yields_the_reply_in_pieces(harness: Harness) -> None:
    pieces = list(harness.replying(REPLY).stream("be precise", "question"))

    assert "".join(pieces) == REPLY
    assert len(pieces) > 1


@pytest.mark.parametrize("call", ["generate", "stream"])
def test_contract_a_server_that_does_not_answer_is_unreachable(harness: Harness, call: str) -> None:
    model = harness.unreachable()

    with pytest.raises(LlmUnreachableError):
        if call == "generate":
            model.generate("s", "p")
        else:
            list(model.stream("s", "p"))
    assert model.is_available() is False


@pytest.mark.parametrize("call", ["generate", "stream"])
def test_contract_a_failing_server_is_a_language_model_error(harness: Harness, call: str) -> None:
    model = harness.failing()

    with pytest.raises(LanguageModelError) as raised:
        if call == "generate":
            model.generate("s", "p")
        else:
            list(model.stream("s", "p"))
    assert not isinstance(raised.value, LlmUnreachableError)


def test_contract_release_and_close_never_fail_after_a_reply(harness: Harness) -> None:
    model = harness.replying(REPLY)
    model.generate("s", "p")

    model.release()
    model.close()
    model.close()  # idempotent


def test_contract_cancel_makes_the_next_call_fail(harness: Harness) -> None:
    model = harness.replying(REPLY)
    assert isinstance(model, Cancellable)

    model.cancel()

    with pytest.raises(LanguageModelError):
        model.generate("s", "p")
