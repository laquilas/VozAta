from __future__ import annotations

from tests.api.conftest import Api


def test_devices_lists_inputs_loopbacks_and_defaults(api: Api) -> None:
    response = api.client.get("/devices")

    assert response.status_code == 200
    assert response.json() == {
        "inputs": [{"id": 9, "name": "Headset Mic", "sample_rate": 48000, "channels": 2}],
        "loopbacks": [
            {"id": 10, "name": "Speakers [Loopback]", "sample_rate": 48000, "channels": 2}
        ],
        "default_input_id": 9,
        "default_loopback_id": 10,
    }


def test_devices_without_defaults(api: Api) -> None:
    api.devices.has_defaults = False

    body = api.client.get("/devices").json()

    assert (body["default_input_id"], body["default_loopback_id"]) == (None, None)
