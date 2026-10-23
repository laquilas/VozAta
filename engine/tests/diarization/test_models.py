from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from vozata.diarization import models
from vozata.diarization.runtime import SpeakerRuntime


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


def test_the_packaged_engine_has_the_extra_once_its_runtime_is_ready(tmp_path: Path) -> None:
    runtime = SpeakerRuntime(tmp_path, tmp_path / "bundle")
    assert models.has_extra(runtime) is False

    (tmp_path / "venv" / "Scripts").mkdir(parents=True)
    (tmp_path / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    (tmp_path / "ready.json").write_text("{}", encoding="utf-8")

    assert models.has_extra(runtime) is True


def test_in_development_the_runtime_is_not_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    assert models.has_extra(SpeakerRuntime(tmp_path, None)) is True
