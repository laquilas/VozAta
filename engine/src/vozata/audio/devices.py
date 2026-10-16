"""Audio device discovery over PyAudioWPatch (WASAPI inputs and loopbacks).

Every function takes an optional PyAudio instance (tests pass a fake); without one, a temporary
instance is created and terminated.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

PA_WASAPI = 13  # PortAudio host API type id for WASAPI


@dataclass(frozen=True)
class DeviceInfo:
    id: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool


def _to_device(info: Mapping[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        id=int(info["index"]),
        name=str(info["name"]),
        channels=int(info["maxInputChannels"]),
        sample_rate=int(info["defaultSampleRate"]),
        is_loopback=bool(info.get("isLoopbackDevice", False)),
    )


@contextmanager
def _session(pa: Any | None) -> Iterator[Any]:
    if pa is not None:
        yield pa
        return
    import pyaudiowpatch  # pragma: no cover - hardware

    instance = pyaudiowpatch.PyAudio()  # pragma: no cover - hardware
    try:  # pragma: no cover - hardware
        yield instance
    finally:  # pragma: no cover - hardware
        instance.terminate()


def list_input_devices(pa: Any | None = None) -> list[DeviceInfo]:
    """WASAPI capture devices (microphones), excluding loopbacks."""
    with _session(pa) as audio:
        wasapi = audio.get_host_api_info_by_type(PA_WASAPI)["index"]
        devices = (audio.get_device_info_by_index(i) for i in range(audio.get_device_count()))
        return [
            _to_device(info)
            for info in devices
            if info["hostApi"] == wasapi
            and info["maxInputChannels"] > 0
            and not info.get("isLoopbackDevice", False)
        ]


def list_loopback_devices(pa: Any | None = None) -> list[DeviceInfo]:
    """WASAPI loopback devices (what each output device plays)."""
    with _session(pa) as audio:
        return [_to_device(info) for info in audio.get_loopback_device_info_generator()]


def default_input(pa: Any | None = None) -> DeviceInfo:
    """The WASAPI default microphone, or the system default when WASAPI has none."""
    with _session(pa) as audio:
        index = audio.get_host_api_info_by_type(PA_WASAPI)["defaultInputDevice"]
        if index >= 0:
            return _to_device(audio.get_device_info_by_index(index))
        return _to_device(audio.get_default_input_device_info())


def default_loopback(pa: Any | None = None) -> DeviceInfo:
    """The loopback of the default output device."""
    with _session(pa) as audio:
        return _to_device(audio.get_default_wasapi_loopback())


def find_device(device_id: int, pa: Any | None = None) -> DeviceInfo:
    """The capture-capable device with this id; `LookupError` if absent or output-only."""
    with _session(pa) as audio:
        try:
            info = audio.get_device_info_by_index(device_id)
        except OSError:
            raise LookupError(f"No audio device with id {device_id}") from None
        if info["maxInputChannels"] <= 0:
            raise LookupError(f"Audio device {device_id} cannot capture")
        return _to_device(info)
