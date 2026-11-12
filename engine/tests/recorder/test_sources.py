from __future__ import annotations

from typing import Any

import pytest

from tests.audio.test_devices import FakePyAudio, _device
from vozata.audio.devices import DeviceInfo
from vozata.domain import Channel
from vozata.recorder.sources import (
    SourceSpec,
    build_sources,
    by_kind,
    excluded,
    match_saved,
    resolve_sources,
    slug,
    source_id,
)

JBL = DeviceInfo(20, "Microfone (5- JBL Quantum Stream)", 1, 48000, False)
INTEL = DeviceInfo(14, "Matriz de microfones (Intel® Smart Sound)", 2, 48000, False)
JBL_OUT = DeviceInfo(23, "Fones de ouvido (JBL) [Loopback]", 2, 48000, True)
REALTEK = DeviceInfo(24, "Alto-falantes (2- Realtek(R) Audio) [Loopback]", 2, 48000, True)


def _direct(function: Any) -> Any:
    return function()


def test_slug_is_ascii_words_without_the_loopback_suffix() -> None:
    assert (
        slug("Alto-falantes (2- Realtek(R) Audio) [Loopback]") == "alto-falantes-2-realtek-r-audio"
    )
    assert (
        slug("Matriz de microfones (Intel® Smart Sound)")
        == "matriz-de-microfones-intel-smart-sound"
    )
    assert slug("Áudio ç") == "audio-c"
    assert slug("***") == "device"


def test_source_id_is_prefixed_by_kind_and_unique() -> None:
    assert source_id(Channel.MIC, "USB mic") == "in-usb-mic"
    assert source_id(Channel.SYSTEM, "Speakers [Loopback]") == "out-speakers"
    assert source_id(Channel.MIC, "USB mic", ["in-usb-mic"]) == "in-usb-mic-2"
    assert source_id(Channel.MIC, "USB mic", ["in-usb-mic", "in-usb-mic-2"]) == "in-usb-mic-3"


def test_excluded_matches_a_substring_case_insensitively() -> None:
    assert excluded("Stereo Mix (Realtek)", ["stereo mix"])
    assert not excluded("USB mic", ["stereo mix", " ", ""])


def test_build_sources_puts_the_preferred_device_of_each_kind_first() -> None:
    specs = build_sources(
        [INTEL, JBL], [REALTEK, JBL_OUT], {Channel.MIC: JBL, Channel.SYSTEM: JBL_OUT}
    )
    assert [(s.source_id, s.preferred) for s in specs] == [
        ("in-microfone-5-jbl-quantum-stream", True),
        ("in-matriz-de-microfones-intel-smart-sound", False),
        ("out-fones-de-ouvido-jbl", True),
        ("out-alto-falantes-2-realtek-r-audio", False),
    ]
    assert [s.kind for s in by_kind(specs, Channel.SYSTEM)] == [Channel.SYSTEM, Channel.SYSTEM]
    assert specs[0].name == JBL.name


def test_build_sources_excludes_by_pattern_but_keeps_the_preferred_device() -> None:
    specs = build_sources(
        [INTEL, JBL], [REALTEK], {Channel.MIC: INTEL, Channel.SYSTEM: None}, ["intel", "realtek"]
    )
    assert [s.device.id for s in specs] == [14, 20]


def test_build_sources_adds_a_preferred_device_missing_from_the_list() -> None:
    specs = build_sources([], [REALTEK], {Channel.MIC: JBL, Channel.SYSTEM: None})
    assert [(s.device.id, s.preferred) for s in specs] == [(20, True), (24, False)]


def test_resolve_sources_lists_every_input_and_loopback() -> None:
    specs = resolve_sources(_direct, FakePyAudio(), None, None)
    assert [(s.source_id, s.kind, s.preferred) for s in specs] == [
        ("in-headset-mic", Channel.MIC, True),
        ("in-usb-mic", Channel.MIC, False),
        ("out-speakers", Channel.SYSTEM, True),
    ]


def test_resolve_sources_prefers_the_chosen_ids() -> None:
    specs = resolve_sources(_direct, FakePyAudio(), 4, None)
    assert specs[0].source_id == "in-usb-mic" and specs[0].preferred


def test_resolve_sources_raises_for_a_chosen_id_that_is_gone() -> None:
    with pytest.raises(LookupError):
        resolve_sources(_direct, FakePyAudio(), 99, None)


def test_resolve_sources_without_any_device() -> None:
    class Empty(FakePyAudio):
        def __init__(self) -> None:
            super().__init__(default_wasapi_input=-1)
            self.devices = [_device(0, "MME", 0, 0)]

        def get_default_wasapi_loopback(self) -> dict[str, Any]:
            raise OSError("none")

        def get_default_input_device_info(self) -> dict[str, Any]:
            raise OSError("none")

    assert resolve_sources(_direct, Empty(), None, None) == []


def test_match_saved_finds_each_saved_source_by_kind_and_name() -> None:
    specs = build_sources(
        [DeviceInfo(31, JBL.name, 1, 48000, False)],
        [REALTEK],
        {Channel.MIC: None, Channel.SYSTEM: None},
    )
    saved = {
        "in-old-id": {"kind": "mic", "name": JBL.name},
        "out-gone": {"kind": "system", "name": "Unplugged [Loopback]"},
    }
    found = match_saved(saved, specs)
    assert list(found) == ["in-old-id"]
    assert found["in-old-id"] == SourceSpec("in-old-id", Channel.MIC, specs[0].device, False)
