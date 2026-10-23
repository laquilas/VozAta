from __future__ import annotations

import httpx
import pytest

from vozata.ports import WorkerUnreachableError
from vozata.worker_client.pairing import PairedWorker, PairingRefusedError, pair_with_worker

URL = "http://192.168.0.20:8766/"


def _pair(handler, code: str = "123456") -> PairedWorker:  # type: ignore[no-untyped-def]
    return pair_with_worker(URL, code, httpx.MockTransport(handler))


def test_the_code_buys_the_token() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"token": "t0k", "id": "4f1c", "name": "GPU-PC"})

    paired = _pair(handle)

    assert paired == PairedWorker("4f1c", "GPU-PC", "t0k")
    assert (str(seen[0].url), seen[0].content) == (
        "http://192.168.0.20:8766/pair",
        b'{"code":"123456"}',
    )


@pytest.mark.parametrize(
    "code", ["worker_pairing_refused", "worker_pairing_locked", "worker_no_token"]
)
def test_a_refusal_names_its_reason(code: str) -> None:
    with pytest.raises(PairingRefusedError) as caught:
        _pair(lambda request: httpx.Response(403, json={"error": {"code": code}}))

    assert caught.value.code == code


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json={"detail": "Not Found"}),
        httpx.Response(500, json=[]),
        httpx.Response(200, text="<html>router</html>"),
    ],
)
def test_something_else_at_that_address_is_not_a_worker(answer: httpx.Response) -> None:
    with pytest.raises(WorkerUnreachableError) as caught:
        _pair(lambda request: answer)

    assert caught.value.host == "192.168.0.20"


def test_an_address_that_does_not_answer_is_unreachable() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(WorkerUnreachableError):
        _pair(refused)
