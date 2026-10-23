from __future__ import annotations

import importlib.util

import pytest

from vozata.diarization import models


@pytest.mark.parametrize(
    ("installed", "expected"),
    [({"torch", "pyannote.audio"}, True), ({"torch"}, False), ({"pyannote.audio"}, False)],
)
def test_the_extra_needs_torch_and_pyannote(
    monkeypatch: pytest.MonkeyPatch, installed: set[str], expected: bool
) -> None:
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if name in installed else None
    )

    assert models.has_extra() is expected


def test_a_missing_parent_package_is_no_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    def find_spec(name: str) -> object:
        raise ModuleNotFoundError(name)  # find_spec("pyannote.audio") without `pyannote`

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)

    assert models.has_extra() is False
