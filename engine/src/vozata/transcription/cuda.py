"""Make the pip-installed CUDA libraries (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) loadable.

CTranslate2 loads cuBLAS and cuDNN lazily on the first GPU transcription; on Windows their `bin`
folders must be on the DLL search path first. This adjusts the process runtime, not configuration.
"""

from __future__ import annotations

import os
import site
import sys
from collections.abc import Iterable
from pathlib import Path

_LIBRARIES = ("cublas", "cudnn")
_registered: set[str] = set()


def register_cuda_dlls(site_dirs: Iterable[Path] | None = None) -> None:
    """Add every existing `nvidia/<lib>/bin` folder to the DLL search path (idempotent)."""
    if site_dirs is None:
        site_dirs = [Path(p) for p in [*site.getsitepackages(), site.getusersitepackages()]]
        if getattr(sys, "frozen", False):  # PyInstaller bundle: the DLLs ship inside it
            site_dirs.append(Path(sys._MEIPASS))
    for root in site_dirs:
        for library in _LIBRARIES:
            folder = str(Path(root) / "nvidia" / library / "bin")
            if folder in _registered or not os.path.isdir(folder):
                continue
            os.add_dll_directory(folder)
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            _registered.add(folder)
