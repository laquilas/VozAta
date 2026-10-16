from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from vozata.transcription.retry import TranscriptionRequestError, send_with_retry

REQUEST = httpx.Request("POST", "https://api.example.test/v1/audio/transcriptions")


class Sequence:
    """Answers with the given responses / exceptions in order; records sleeps."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.sleeps: list[float] = []

    def send(self) -> httpx.Response:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def run(self, **options: object) -> httpx.Response:
        return send_with_retry(self.send, sleep=self.sleeps.append, **options)  # type: ignore[arg-type]


def response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=REQUEST)


def test_a_success_is_returned_at_once() -> None:
    calls = Sequence(response(200))

    assert calls.run().status_code == 200
    assert (calls.calls, calls.sleeps) == (1, [])


def test_rate_limits_wait_for_retry_after() -> None:
    calls = Sequence(response(429, {"Retry-After": "7"}), response(200))

    assert calls.run().status_code == 200
    assert calls.sleeps == [7.0]


def test_server_errors_and_timeouts_back_off_exponentially() -> None:
    calls = Sequence(response(503), httpx.ReadTimeout("slow", request=REQUEST), response(200))

    assert calls.run(base_delay=0.5).status_code == 200
    assert calls.sleeps == [0.5, 1.0]


def test_retry_after_is_capped_and_a_bad_value_falls_back_to_the_backoff() -> None:
    capped = Sequence(response(429, {"Retry-After": "3600"}), response(200))
    capped.run(max_delay=20)
    garbled = Sequence(response(429, {"Retry-After": "soon"}), response(200))
    garbled.run(base_delay=2)

    assert (capped.sleeps, garbled.sleeps) == ([20.0], [2.0])


@pytest.mark.parametrize(
    ("outcomes", "reason"),
    [
        ((response(429),) * 3, "HTTP 429"),
        ((httpx.ConnectError("refused", request=REQUEST),) * 3, "refused"),
    ],
)
def test_it_gives_up_after_three_attempts_with_a_clear_error(
    outcomes: tuple[httpx.Response | Exception, ...], reason: str
) -> None:
    calls = Sequence(*outcomes)

    with pytest.raises(TranscriptionRequestError, match=f"after 3 attempts.*{reason}"):
        calls.run()

    assert calls.calls == 3
    assert len(calls.sleeps) == 2


def test_client_errors_are_not_retried() -> None:
    calls = Sequence(response(401))

    assert calls.run().status_code == 401
    assert calls.calls == 1


def test_the_default_sleep_is_time_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import vozata.transcription.retry as module

    slept: list[float] = []
    monkeypatch.setattr(module.time, "sleep", slept.append)
    outcomes = [response(500), response(200)]
    send: Callable[[], httpx.Response] = lambda: outcomes.pop(0)  # noqa: E731

    send_with_retry(send, base_delay=0.25)

    assert slept == [0.25]
