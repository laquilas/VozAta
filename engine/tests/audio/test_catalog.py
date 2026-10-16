from __future__ import annotations

from typing import Any

import pytest

from vozata.audio import catalog as catalog_module
from vozata.audio.catalog import WasapiCatalog
from vozata.audio.devices import DeviceInfo

MIC = DeviceInfo(9, "Mic", 1, 48000, False)


class _Audio:
    instances: list[_Audio] = []

    def __init__(self) -> None:
        self.pa = object()
        self.closed = False
        _Audio.instances.append(self)

    def call(self, function: Any) -> Any:
        return function()

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset() -> None:
    _Audio.instances = []


def test_each_query_runs_on_a_fresh_portaudio_thread_that_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[object] = []
    monkeypatch.setattr(
        catalog_module.devices, "list_input_devices", lambda pa: received.append(pa) or [MIC]
    )
    monkeypatch.setattr(catalog_module.devices, "list_loopback_devices", lambda pa: [])
    catalog = WasapiCatalog(_Audio)

    assert catalog.inputs() == [MIC]
    assert catalog.loopbacks() == []

    assert len(_Audio.instances) == 2
    assert all(audio.closed for audio in _Audio.instances)
    assert received == [_Audio.instances[0].pa]


def test_defaults_are_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(pa: object) -> DeviceInfo:
        raise OSError("No Default Input Device Available")

    monkeypatch.setattr(catalog_module.devices, "default_input", missing)
    monkeypatch.setattr(catalog_module.devices, "default_loopback", lambda pa: MIC)
    catalog = WasapiCatalog(_Audio)

    assert catalog.default_input() is None
    assert catalog.default_loopback() == MIC
    assert all(audio.closed for audio in _Audio.instances)
