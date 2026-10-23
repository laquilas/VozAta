from __future__ import annotations

import os
from pathlib import Path

import pytest

from vozata.transcription import cuda


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    for library in ("cublas", "cudnn"):
        (tmp_path / "nvidia" / library / "bin").mkdir(parents=True)
    added: list[str] = []
    monkeypatch.setattr(cuda, "_registered", set())
    monkeypatch.setattr(os, "add_dll_directory", added.append, raising=False)
    monkeypatch.setenv("PATH", "C:/existing")
    return tmp_path, added


def test_registers_cublas_and_cudnn_bin_folders(site: tuple[Path, list[str]]) -> None:
    root, added = site

    cuda.register_cuda_dlls([root])

    expected = [str(root / "nvidia" / name / "bin") for name in ("cublas", "cudnn")]
    assert added == expected
    assert os.environ["PATH"].split(os.pathsep)[:2] == expected[::-1]


def test_registration_is_idempotent(site: tuple[Path, list[str]]) -> None:
    root, added = site

    cuda.register_cuda_dlls([root])
    cuda.register_cuda_dlls([root])

    assert len(added) == 2


def test_missing_folders_are_skipped(tmp_path: Path, site: tuple[Path, list[str]]) -> None:
    _, added = site

    cuda.register_cuda_dlls([tmp_path / "elsewhere"])

    assert added == []


def test_defaults_to_the_interpreter_site_packages(
    site: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, added = site
    monkeypatch.setattr(cuda.site, "getsitepackages", lambda: [str(root)])
    monkeypatch.setattr(cuda.site, "getusersitepackages", lambda: str(root / "user"))

    cuda.register_cuda_dlls()

    assert len(added) == 2


def test_the_downloaded_runtime_is_registered_too(
    site: tuple[Path, list[str]], tmp_path: Path
) -> None:
    root, added = site

    found = cuda.register_cuda_dlls([tmp_path / "no-site"], extra=[root])

    assert found is True
    assert added == [str(root / "nvidia" / name / "bin") for name in ("cublas", "cudnn")]


def test_nothing_found_is_false(site: tuple[Path, list[str]], tmp_path: Path) -> None:
    assert cuda.register_cuda_dlls([tmp_path / "a"], extra=[tmp_path / "b"]) is False


def test_packaged_reads_the_frozen_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    assert cuda.packaged() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert cuda.packaged() is True
