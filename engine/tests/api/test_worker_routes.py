from __future__ import annotations

import dataclasses

from tests.api.conftest import Api
from vozata.ports import WorkerUnreachableError
from vozata.worker_client.discovery import FoundWorker
from vozata.worker_client.pairing import PairedWorker, PairingRefusedError


def _replace(api: Api, **changes: object) -> None:
    api.app.state.container = dataclasses.replace(api.app.state.container, **changes)


def test_discover_lists_the_workers_that_answered(api: Api) -> None:
    ports: list[int] = []
    found = [FoundWorker("4f1c", "GPU-PC", "http://192.168.0.20:8766", "0.9.0", "RTX 4070")]
    _replace(
        api, discover_workers=lambda current: ports.append(current.worker_discovery_port) or found
    )

    response = api.client.get("/worker/discover")

    assert response.status_code == 200
    assert response.json() == {
        "workers": [
            {
                "id": "4f1c",
                "name": "GPU-PC",
                "url": "http://192.168.0.20:8766",
                "version": "0.9.0",
                "gpu": "RTX 4070",
            }
        ]
    }
    assert ports == [8767]


def test_pairing_saves_the_address_token_and_id(api: Api) -> None:
    asked: list[tuple[str, str]] = []

    def pair(url: str, code: str) -> PairedWorker:
        asked.append((url, code))
        return PairedWorker("4f1c", "GPU-PC", "secret-token")

    _replace(api, pair_worker=pair)

    response = api.client.post(
        "/worker/pair", json={"url": "http://192.168.0.20:8766", "code": "123456"}
    )

    assert response.status_code == 200
    assert response.json() == {"id": "4f1c", "name": "GPU-PC", "url": "http://192.168.0.20:8766"}
    assert asked == [("http://192.168.0.20:8766", "123456")]
    current = api.settings_file.current
    assert (current.worker_url, current.worker_token, current.worker_id) == (
        "http://192.168.0.20:8766",
        "secret-token",
        "4f1c",
    )
    values = api.client.get("/settings").json()["values"]
    assert values["WORKER_TOKEN"] != "secret-token"  # masked like every secret


def test_a_refused_code_is_a_localized_conflict(api: Api) -> None:
    def refuse(url: str, code: str) -> PairedWorker:
        raise PairingRefusedError("worker_pairing_refused")

    _replace(api, pair_worker=refuse)

    response = api.client.post("/worker/pair", json={"url": "http://gpu:8766", "code": "000000"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "worker_pairing_refused"
    assert "code" in response.json()["error"]["message"]
    assert api.settings_file.current.worker_url is None


def test_an_unreachable_worker_names_its_host(api: Api) -> None:
    def unreachable(url: str, code: str) -> PairedWorker:
        raise WorkerUnreachableError("gpu", "refused")

    _replace(api, pair_worker=unreachable)

    response = api.client.post("/worker/pair", json={"url": "http://gpu:8766", "code": "1"})

    assert response.status_code == 502
    assert "gpu" in response.json()["error"]["message"]


def test_a_pairing_address_must_be_http(api: Api) -> None:
    response = api.client.post("/worker/pair", json={"url": "gpu:8766", "code": "123456"})

    assert response.status_code == 422
