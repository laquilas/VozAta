"""Make the pip-installed CUDA libraries (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) loadable.

CTranslate2 loads cuBLAS and cuDNN lazily on the first GPU transcription; on Windows their `bin`
folders must be on the DLL search path first. This adjusts the process runtime, not configuration.
The packaged engine has them only once they were downloaded (phase 58, `cuda_runtime.py`).
"""

from __future__ import annotations

import os
import site
import sys
from collections.abc import Iterable
from pathlib import Path

_LIBRARIES = ("cublas", "cudnn")
_registered: set[str] = set()


def register_cuda_dlls(site_dirs: Iterable[Path] | None = None, extra: Iterable[Path] = ()) -> bool:
    """Add every existing `nvidia/<lib>/bin` folder (of `site_dirs`, default the interpreter's
    site-packages, and of `extra`, the downloaded CUDA runtime) to the DLL search path
    (idempotent). True when any CUDA folder is registered."""
    if site_dirs is None:
        site_dirs = [Path(p) for p in [*site.getsitepackages(), site.getusersitepackages()]]
    for root in [*site_dirs, *extra]:
        for library in _LIBRARIES:
            folder = str(Path(root) / "nvidia" / library / "bin")
            if folder in _registered or not os.path.isdir(folder):
                continue
            os.add_dll_directory(folder)
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            _registered.add(folder)
    return bool(_registered)


def packaged() -> bool:
    """Running as the PyInstaller-built engine (no pip CUDA wheels next to it)."""
    return bool(getattr(sys, "frozen", False))
