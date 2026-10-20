"""A session folder as a ZIP (phase 39): one top-level folder named after the session id.

WAVs are stored as they are (PCM barely compresses); the texts are deflated.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

MEDIA_TYPE = "application/zip"


def zip_folder(folder: Path, destination: Path) -> None:
    """Write the files of `folder` (not its subfolders) as `<folder name>/<file>` entries."""
    with ZipFile(destination, "w") as archive:
        for path in sorted(item for item in folder.iterdir() if item.is_file()):
            compression = ZIP_STORED if path.suffix == ".wav" else ZIP_DEFLATED
            archive.write(path, f"{folder.name}/{path.name}", compress_type=compression)
