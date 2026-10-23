from __future__ import annotations

import httpx
import pytest

from vozata.worker_client.status import WorkerStatus, worker_status

URL = "http://gpu-pc:8766/"


def _transport(handler) -> httpx.MockTransport:  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


def test_a_worker_that_answers_reports_its_version_and_models() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"version": "0.9.0", "models": ["large-v3-turbo"]})

    status = worker_status(URL, "t0k", _transport(handle))

    assert status == WorkerStatus(True, "0.9.0", ["large-v3-turbo"])
    assert (seen[0].url.path, seen[0].headers["authorization"]) == ("/health", "Bearer t0k")


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(401),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"version": "1"}),  # no models: not a worker
    ],
)
def test_a_refusal_or_another_service_is_not_reachable(answer: httpx.Response) -> None:
    assert worker_status(URL, None, _transport(lambda request: answer)) == WorkerStatus(False)


def test_a_worker_that_is_off_is_not_reachable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert worker_status(URL, None, _transport(handle)) == WorkerStatus(False)
