from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from vozata.audio.devices import (
    DeviceInfo,
    default_input,
    default_loopback,
    find_device,
    list_input_devices,
    list_loopback_devices,
)

WASAPI = 2


def _device(index: int, name: str, host: int, inputs: int, loopback: bool = False) -> dict:
    return {
        "index": index,
        "name": name,
        "hostApi": host,
        "maxInputChannels": inputs,
        "defaultSampleRate": 48000.0,
        "isLoopbackDevice": loopback,
    }


class FakePyAudio:
    def __init__(self, default_wasapi_input: int = 2) -> None:
        self.devices = [
            _device(0, "MME mic", 0, 2),
            _device(1, "Speakers", WASAPI, 0),
            _device(2, "Headset mic", WASAPI, 1),
            _device(3, "Speakers [Loopback]", WASAPI, 2, loopback=True),
            _device(4, "USB mic", WASAPI, 2),
        ]
        self.default_wasapi_input = default_wasapi_input

    def get_host_api_info_by_type(self, host_type: int) -> dict[str, Any]:
        return {"index": WASAPI, "defaultInputDevice": self.default_wasapi_input}

    def get_device_count(self) -> int:
        return len(self.devices)

    def get_device_info_by_index(self, index: int) -> dict[str, Any]:
        if not 0 <= index < len(self.devices):
            raise OSError("Invalid device index")
        return self.devices[index]

    def get_loopback_device_info_generator(self) -> Iterator[dict[str, Any]]:
        return (device for device in self.devices if device["isLoopbackDevice"])

    def get_default_wasapi_loopback(self) -> dict[str, Any]:
        return self.devices[3]

    def get_default_input_device_info(self) -> dict[str, Any]:
        return self.devices[0]


def test_input_devices_are_wasapi_inputs_without_loopbacks() -> None:
    devices = list_input_devices(FakePyAudio())

    assert [device.name for device in devices] == ["Headset mic", "USB mic"]
    assert devices[0] == DeviceInfo(
        id=2, name="Headset mic", channels=1, sample_rate=48000, is_loopback=False
    )


def test_loopback_devices_are_listed() -> None:
    devices = list_loopback_devices(FakePyAudio())

    assert [(device.id, device.is_loopback) for device in devices] == [(3, True)]


def test_default_input_is_the_wasapi_default() -> None:
    assert default_input(FakePyAudio()).id == 2


def test_default_input_falls_back_to_the_system_default_without_a_wasapi_one() -> None:
    assert default_input(FakePyAudio(default_wasapi_input=-1)).id == 0


def test_default_loopback() -> None:
    assert default_loopback(FakePyAudio()).name == "Speakers [Loopback]"


def test_find_device_by_id() -> None:
    assert find_device(4, FakePyAudio()).channels == 2


def test_find_device_with_an_unknown_id_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        find_device(99, FakePyAudio())


def test_device_without_input_channels_is_rejected() -> None:
    with pytest.raises(LookupError):
        find_device(1, FakePyAudio())
