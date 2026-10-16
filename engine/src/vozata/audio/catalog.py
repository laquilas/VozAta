"""Device listing for the API (`DeviceCatalog`), each query on its own PortAudio thread.

A recording session keeps its own `PortAudioThread`; listings never share it, because PortAudio
must be initialized, used and terminated on one thread (see `portaudio.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vozata.audio import devices
from vozata.audio.devices import DeviceInfo
from vozata.audio.portaudio import PortAudioThread


class WasapiCatalog:
    def __init__(self, audio_factory: Callable[[], PortAudioThread] = PortAudioThread) -> None:
        self._audio_factory = audio_factory

    def inputs(self) -> list[DeviceInfo]:
        return self._query(devices.list_input_devices)

    def loopbacks(self) -> list[DeviceInfo]:
        return self._query(devices.list_loopback_devices)

    def default_input(self) -> DeviceInfo | None:
        return self._query_or_none(devices.default_input)

    def default_loopback(self) -> DeviceInfo | None:
        return self._query_or_none(devices.default_loopback)

    def _query(self, function: Callable[[Any], Any]) -> Any:
        audio = self._audio_factory()
        try:
            return audio.call(lambda: function(audio.pa))
        finally:
            audio.close()

    def _query_or_none(self, function: Callable[[Any], DeviceInfo]) -> DeviceInfo | None:
        try:
            return self._query(function)
        except (OSError, LookupError):  # no default device (e.g. nothing plugged in)
            return None
