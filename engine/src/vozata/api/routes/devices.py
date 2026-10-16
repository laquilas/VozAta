"""`GET /devices`: WASAPI microphones and loopbacks with the defaults."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from vozata.api.container import ApiContainer
from vozata.api.deps import container
from vozata.api.schemas import Device, Devices
from vozata.audio.devices import DeviceInfo

router = APIRouter(tags=["devices"])


def _device(info: DeviceInfo) -> Device:
    return Device(id=info.id, name=info.name, sample_rate=info.sample_rate, channels=info.channels)


@router.get("/devices", response_model=Devices)
def devices(c: Annotated[ApiContainer, Depends(container)]) -> Devices:
    catalog = c.devices
    default_input, default_loopback = catalog.default_input(), catalog.default_loopback()
    return Devices(
        inputs=[_device(info) for info in catalog.inputs()],
        loopbacks=[_device(info) for info in catalog.loopbacks()],
        default_input_id=default_input.id if default_input else None,
        default_loopback_id=default_loopback.id if default_loopback else None,
    )
