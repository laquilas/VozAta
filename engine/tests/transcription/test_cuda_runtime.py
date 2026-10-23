from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from vozata.transcription.cuda_runtime import (
    WHEELS,
    CudaDownloadError,
    CudaRuntime,
    Wheel,
    extract_dlls,
    find_wheel,
    install,
)


def _wheel(library: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"nvidia/{library}/bin/{library}64.dll", b"dll")
        archive.writestr(f"nvidia/{library}/bin/README.txt", b"no")
        archive.writestr(f"nvidia/{library}/include/{library}.h", b"no")
        archive.writestr(f"nvidia_{library}-1.dist-info/METADATA", b"no")
    return buffer.getvalue()


class _PyPI:
    """Answers the PyPI JSON API and the file downloads for `WHEELS`."""

    def __init__(self, *, bad_digest: bool = False, missing: str | None = None) -> None:
        self.files = {name: _wheel(name.split("-")[1]) for name, _ in WHEELS}
        self.bad_digest = bad_digest
        self.missing = missing
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        for name, version in WHEELS:
            if url == f"https://pypi.org/pypi/{name}/{version}/json":
                if name == self.missing:
                    return httpx.Response(404)
                data = self.files[name]
                digest = "0" * 64 if self.bad_digest else hashlib.sha256(data).hexdigest()
                filename = f"{name.replace('-', '_')}-{version}-py3-none-win_amd64.whl"
                return httpx.Response(
                    200,
                    json={
                        "urls": [
                            {"filename": "x-manylinux.whl", "url": "-", "digests": {}, "size": 0},
                            {
                                "filename": filename,
                                "url": f"https://files.test/{name}.whl",
                                "digests": {"sha256": digest},
                                "size": len(data),
                            },
                        ]
                    },
                )
            if url == f"https://files.test/{name}.whl":
                return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)


def _install(tmp_path: Path, pypi: _PyPI) -> tuple[bool, CudaRuntime, list[tuple[str, dict]]]:
    runtime, said = CudaRuntime(tmp_path / "cuda"), []
    with httpx.Client(transport=httpx.MockTransport(pypi)) as client:
        ok = install(runtime, client, lambda key, **params: said.append((key, params)))
    return ok, runtime, said


def test_install_downloads_checks_and_extracts_only_the_dlls(tmp_path: Path) -> None:
    ok, runtime, said = _install(tmp_path, _PyPI())

    assert ok and runtime.is_ready()
    files = sorted(
        p.relative_to(runtime.root).as_posix() for p in runtime.root.rglob("*") if p.is_file()
    )
    assert files == ["nvidia/cublas/bin/cublas64.dll", "nvidia/cudnn/bin/cudnn64.dll", "ready.json"]
    assert runtime.details() == dict(WHEELS)
    keys = [key for key, _ in said]
    assert keys[0] == "start" and keys[-1] == "done"
    assert keys.count("step_download") == 2 and keys.count("step_extract") == 2
    assert ("progress", {"name": "nvidia-cudnn-cu12", "percent": 100}) in said


def test_a_wrong_digest_leaves_nothing_ready(tmp_path: Path) -> None:
    ok, runtime, said = _install(tmp_path, _PyPI(bad_digest=True))

    assert not ok and not runtime.is_ready()
    assert said[-1][0] == "failed"
    assert "SHA-256" in str(said[-1][1]["reason"])
    assert not list((runtime.root / "downloads").glob("*"))


def test_a_wheel_missing_on_pypi_fails(tmp_path: Path) -> None:
    ok, _, said = _install(tmp_path, _PyPI(missing="nvidia-cudnn-cu12"))

    assert not ok
    assert "404" in str(said[-1][1]["reason"])


def test_a_ready_runtime_is_kept(tmp_path: Path) -> None:
    pypi = _PyPI()
    _install(tmp_path, pypi)
    requests = len(pypi.requests)

    ok, _, said = _install(tmp_path, pypi)

    assert ok and said == [("already_ready", {"folder": tmp_path / "cuda"})]
    assert len(pypi.requests) == requests


def test_find_wheel_without_a_windows_file_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"urls": [{"filename": "a-manylinux.whl"}]})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(CudaDownloadError, match="win_amd64"),
    ):
        find_wheel(client, "nvidia-cublas-cu12", "1")


def test_a_failed_download_is_reported(tmp_path: Path) -> None:
    pypi = _PyPI()
    real = pypi.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500) if "files.test" in str(request.url) else real(request)

    runtime, said = CudaRuntime(tmp_path / "cuda"), []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ok = install(runtime, client, lambda key, **params: said.append((key, params)))

    assert not ok
    assert "HTTP 500" in str(said[-1][1]["reason"])


def test_extract_skips_other_files(tmp_path: Path) -> None:
    wheel = tmp_path / "w.whl"
    wheel.write_bytes(_wheel("cublas"))

    assert extract_dlls(wheel, tmp_path / "out") == 1


@pytest.mark.parametrize("marker", ["no json", "[1]"])
def test_unreadable_details_are_empty(tmp_path: Path, marker: str) -> None:
    runtime = CudaRuntime(tmp_path)
    runtime.marker.write_text(marker, encoding="utf-8")

    assert runtime.details() == {}


def test_wheel_is_a_value() -> None:
    assert Wheel("a", "u", "d", 1) == Wheel("a", "u", "d", 1)


def test_the_pinned_versions_match_the_marker(tmp_path: Path) -> None:
    ok, runtime, _ = _install(tmp_path, _PyPI())

    assert ok
    assert (
        json.loads(runtime.marker.read_text(encoding="utf-8"))["nvidia-cudnn-cu12"] == "9.27.0.42"
    )
