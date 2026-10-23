from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from vozata import __version__
from vozata.api.system_info import GpuInfo
from vozata.worker.app import create_worker_app
from vozata.worker.local import WorkerIdentity, is_loopback_client, lan_addresses
from vozata.worker.pairing import PairingCodes
from vozata.worker.speech import LoadedModel, SpeechService

TOKEN = "s3cret-token"
IDENTITY = WorkerIdentity("4f1c", "GPU-PC", 8766)


def _client(
    token: str | None = TOKEN, client: tuple[str, int] = ("127.0.0.1", 50000)
) -> TestClient:
    numbers = itertools.count(123456)
    app = create_worker_app(
        token,
        gpu_info=lambda: GpuInfo(True, "RTX 4070", 12282),
        speech=SpeechService(lambda: LoadedModel(None, "")),  # type: ignore[arg-type]
        identity=IDENTITY,
        pairing=PairingCodes(lambda: 0.0, lambda: str(next(numbers))),
        addresses=lambda: ["192.168.0.20"],
    )
    return TestClient(app, client=client)


def test_the_right_code_gives_the_token_without_a_token() -> None:
    response = _client().post("/pair", json={"code": "123456"})

    assert response.status_code == 200
    assert response.json() == {"token": TOKEN, "id": "4f1c", "name": "GPU-PC"}


def test_a_wrong_code_is_refused() -> None:
    response = _client().post("/pair", json={"code": "000000"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        403,
        "worker_pairing_refused",
    )


def test_too_many_wrong_codes_lock_pairing() -> None:
    client = _client()
    for _ in range(5):
        client.post("/pair", json={"code": "000000"})

    response = client.post("/pair", json={"code": "123456"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        423,
        "worker_pairing_locked",
    )


def test_a_worker_without_a_token_has_nothing_to_pair() -> None:
    response = _client(token=None).post("/pair", json={"code": "123456"})

    assert response.json()["error"]["code"] == "worker_no_token"


def test_the_local_status_shows_what_the_worker_app_needs() -> None:
    response = _client().get("/local/status")

    assert response.status_code == 200
    assert response.json() == {
        "version": __version__,
        "id": "4f1c",
        "name": "GPU-PC",
        "port": 8766,
        "addresses": ["192.168.0.20"],
        "token": TOKEN,
        "pairing_code": "123456",
        "code_expires_in": 300,
        "gpu": {"available": True, "name": "RTX 4070", "vram_total_mb": 12282},
        "models": [],
    }


def test_a_loopback_worker_shows_no_pairing_code() -> None:
    body = _client(token=None).get("/local/status").json()

    assert (body["token"], body["pairing_code"], body["code_expires_in"]) == (None, None, None)


@pytest.mark.parametrize("host", ["192.168.0.30", "testclient"])
def test_the_local_status_is_refused_to_other_pcs(host: str) -> None:
    response = _client(client=(host, 50000)).get("/local/status")

    assert (response.status_code, response.json()["error"]["code"]) == (403, "worker_local_only")


def test_the_health_still_needs_the_token() -> None:
    assert _client().get("/health").status_code == 401


@pytest.mark.parametrize(
    ("host", "local"), [("127.0.0.1", True), ("::1", True), ("10.0.0.2", False), (None, False)]
)
def test_loopback_clients(host: str | None, local: bool) -> None:
    assert is_loopback_client(host) is local


def test_lan_addresses_skip_loopback_link_local_and_repeats() -> None:
    found = ["127.0.0.1", "192.168.0.20", "169.254.3.4", "192.168.0.20", "172.26.32.1"]

    assert lan_addresses(lambda host: found, "pc") == ["192.168.0.20", "172.26.32.1"]


def test_lan_addresses_of_an_unknown_host_are_empty() -> None:
    def fail(host: str) -> list[str]:
        raise OSError("no such host")

    assert lan_addresses(fail, "pc") == []
