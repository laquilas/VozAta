"""Zip the engine's source for the speaker runtime (phase 56): the speaker children run with the
runtime's Python and import `vozata` from this zip (on `PYTHONPATH`), so the runtime never holds
its own, possibly older, copy of VozAta.

usage: python packaging/make_source_zip.py engine/src build/dist/vozata-engine/speakers/vozata.zip
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def source_files(src: Path) -> list[Path]:
    """Every file of the `vozata` package except compiled caches, in a stable order."""
    return sorted(
        path
        for path in (src / "vozata").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def make_zip(src: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    files = source_files(src)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(src).as_posix())
    return len(files)


if __name__ == "__main__":
    print(f"{make_zip(Path(sys.argv[1]), Path(sys.argv[2]))} files")
