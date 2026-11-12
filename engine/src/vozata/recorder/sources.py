"""The audio sources of a recording: every input and every loopback (phase 65).

A source has a stable id made from its device name (`in-microfone-jbl-quantum-stream`,
`out-alto-falantes-realtek-audio`), never from the PortAudio index, which changes when a device
is plugged in. An input feeds the `mic` channel, a loopback the `system` channel. The preferred
source of each kind (the UI's choice or the Windows default) is selected first and opened first.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from vozata.audio import devices
from vozata.audio.devices import DeviceInfo
from vozata.domain import Channel

LOOPBACK_SUFFIX = "[Loopback]"
_PREFIX = {Channel.MIC: "in", Channel.SYSTEM: "out"}


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    kind: Channel  # MIC: an input; SYSTEM: a loopback
    device: DeviceInfo
    preferred: bool = False

    @property
    def name(self) -> str:
        return self.device.name


def slug(name: str) -> str:
    """Lower-case ASCII words joined by `-` (`Microfone (5- JBL)` → `microfone-5-jbl`)."""
    if name.endswith(LOOPBACK_SUFFIX):
        name = name[: -len(LOOPBACK_SUFFIX)]
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_name.lower())
    return "-".join(words) or "device"


def source_id(kind: Channel, name: str, taken: Iterable[str] = ()) -> str:
    """`in-<slug>` / `out-<slug>`, with `-2`, `-3`... when two devices share a name."""
    base = f"{_PREFIX[kind]}-{slug(name)}"
    used = set(taken)
    candidate, n = base, 1
    while candidate in used:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def excluded(name: str, patterns: Sequence[str]) -> bool:
    """True when the device name contains one of `patterns` (case-insensitive)."""
    lowered = name.lower()
    return any(pattern.strip().lower() in lowered for pattern in patterns if pattern.strip())


def build_sources(
    inputs: Sequence[DeviceInfo],
    loopbacks: Sequence[DeviceInfo],
    preferred: dict[Channel, DeviceInfo | None],
    exclude: Sequence[str] = (),
) -> list[SourceSpec]:
    """Every device as a source, the preferred one of each kind first.

    A preferred device is kept even when a pattern excludes it (the user chose it).
    """
    specs: list[SourceSpec] = []
    taken: list[str] = []
    for kind, listed in ((Channel.MIC, inputs), (Channel.SYSTEM, loopbacks)):
        choice = preferred.get(kind)
        ordered = sorted(listed, key=lambda info: choice is None or info.id != choice.id)
        if choice is not None and all(info.id != choice.id for info in listed):
            ordered.insert(0, choice)
        for info in ordered:
            is_preferred = choice is not None and info.id == choice.id
            if not is_preferred and excluded(info.name, exclude):
                continue
            identifier = source_id(kind, info.name, taken)
            taken.append(identifier)
            specs.append(SourceSpec(identifier, kind, info, is_preferred))
    return specs


def resolve_sources(
    call: Callable[[Callable[[], Any]], Any],
    pa: Any,
    mic_device: int | None,
    system_device: int | None,
    exclude: Sequence[str] = (),
) -> list[SourceSpec]:
    """Every WASAPI input and loopback; the chosen ids (or the defaults) are preferred.

    `LookupError` when a chosen id is gone. A missing default (nothing plugged in) leaves that
    kind without a preferred source.
    """
    preferred = devices.resolve_devices(call, pa, mic_device, system_device, optional=True)
    inputs = call(lambda: devices.list_input_devices(pa))
    loopbacks = call(lambda: devices.list_loopback_devices(pa))
    return build_sources(inputs, loopbacks, preferred, exclude)


def by_kind(specs: Sequence[SourceSpec], kind: Channel) -> list[SourceSpec]:
    return [spec for spec in specs if spec.kind == kind]


def match_saved(
    saved: dict[str, dict[str, Any]], specs: Sequence[SourceSpec]
) -> dict[str, SourceSpec]:
    """The current device of each saved source id (by name: ids can change), for a resume."""
    by_name = {(spec.kind.value, spec.name): spec for spec in specs}
    found: dict[str, SourceSpec] = {}
    for identifier, entry in saved.items():
        spec = by_name.get((str(entry.get("kind")), str(entry.get("name"))))
        if spec is not None:
            found[identifier] = SourceSpec(identifier, spec.kind, spec.device, spec.preferred)
    return found
