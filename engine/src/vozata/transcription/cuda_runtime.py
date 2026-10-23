"""The CUDA libraries of the packaged engine, downloaded on the PC (phase 58).

The installers no longer carry cuBLAS / cuDNN (1.8 GB). `vozata-engine cuda install` downloads
the same pinned pip wheels the development environment uses from PyPI, checks each against the
SHA-256 PyPI publishes, and extracts only their DLLs into `root/nvidia/<lib>/bin`, the layout
`register_cuda_dlls` looks for. `ready.json` is written last.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

WHEELS = (("nvidia-cublas-cu12", "12.9.2.10"), ("nvidia-cudnn-cu12", "9.27.0.42"))
PYPI = "https://pypi.org/pypi"
PLATFORM = "win_amd64.whl"
CHUNK = 1 << 20

Say = Callable[..., None]  # a step key (`cli.cuda.<key>`) and its parameters


class CudaDownloadError(RuntimeError):
    """A wheel could not be found, downloaded or checked."""


@dataclass(frozen=True)
class Wheel:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class CudaRuntime:
    root: Path  # %LOCALAPPDATA%\VozAta\cuda

    @property
    def marker(self) -> Path:
        return self.root / "ready.json"

    def is_ready(self) -> bool:
        return self.marker.is_file()

    def details(self) -> dict[str, object]:
        try:
            value = json.loads(self.marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


def find_wheel(client: httpx.Client, name: str, version: str) -> Wheel:
    """The Windows x64 wheel of `name==version` on PyPI, with its published SHA-256."""
    response = client.get(f"{PYPI}/{name}/{version}/json")
    if response.status_code != 200:
        raise CudaDownloadError(f"{name} {version}: PyPI answered {response.status_code}")
    for file in response.json().get("urls", []):
        if file.get("filename", "").endswith(PLATFORM):
            return Wheel(file["filename"], file["url"], file["digests"]["sha256"], file["size"])
    raise CudaDownloadError(f"{name} {version}: no {PLATFORM} on PyPI")


def download(
    client: httpx.Client, wheel: Wheel, target: Path, progress: Callable[[int, int], None]
) -> None:
    """Stream `wheel` into `target`; a wrong digest deletes it and raises."""
    digest = hashlib.sha256()
    partial = target.with_suffix(".part")
    done = 0
    with client.stream("GET", wheel.url) as response, partial.open("wb") as out:
        if response.status_code != 200:
            raise CudaDownloadError(f"{wheel.name}: HTTP {response.status_code}")
        for chunk in response.iter_bytes(CHUNK):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(done, wheel.size)
    if digest.hexdigest() != wheel.sha256:
        partial.unlink(missing_ok=True)
        raise CudaDownloadError(f"{wheel.name}: the download does not match PyPI's SHA-256")
    partial.replace(target)


def extract_dlls(wheel_file: Path, root: Path) -> int:
    """Copy the `nvidia/<lib>/bin/*.dll` members of a wheel into `root`; their count."""
    count = 0
    with zipfile.ZipFile(wheel_file) as archive:
        for member in archive.infolist():
            parts = member.filename.split("/")
            if len(parts) == 4 and parts[0] == "nvidia" and parts[2] == "bin":
                if not parts[3].lower().endswith(".dll"):
                    continue
                target = root.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out, CHUNK)
                count += 1
    return count


def install(runtime: CudaRuntime, client: httpx.Client, say: Say) -> bool:
    """Download and extract every wheel; keep a ready runtime. False (said why) on a failure."""
    if runtime.is_ready():
        say("already_ready", folder=runtime.root)
        return True
    downloads = runtime.root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    say("start", folder=runtime.root)
    try:
        for name, version in WHEELS:
            wheel = find_wheel(client, name, version)
            target = downloads / wheel.name
            say("step_download", name=name, size=wheel.size // (1 << 20))
            download(client, wheel, target, _progress(say, name))
            say("step_extract", name=name)
            extract_dlls(target, runtime.root)
            target.unlink()
    except (CudaDownloadError, httpx.HTTPError, OSError, zipfile.BadZipFile) as error:
        say("failed", reason=error)
        return False
    shutil.rmtree(downloads, ignore_errors=True)
    runtime.marker.write_text(json.dumps(dict(WHEELS)), encoding="utf-8")
    say("done", folder=runtime.root)
    return True


def _progress(say: Say, name: str) -> Callable[[int, int], None]:
    """Say every tenth of the download."""
    last = [-1]

    def report(done: int, total: int) -> None:
        tenth = done * 10 // total if total else 0
        if tenth != last[0]:
            last[0] = tenth
            say("progress", name=name, percent=tenth * 10)

    return report
