from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from vozata.export.bundle import zip_folder


def test_the_folder_files_are_zipped_under_the_folder_name(tmp_path: Path) -> None:
    folder = tmp_path / "20261019_171444"
    folder.mkdir()
    (folder / "session.json").write_text("{}", encoding="utf-8")
    (folder / "mic.wav").write_bytes(b"RIFF" + bytes(100))
    (folder / "nested").mkdir()
    destination = tmp_path / "out.zip"

    zip_folder(folder, destination)

    with ZipFile(destination) as archive:
        entries = {info.filename: info.compress_type for info in archive.infolist()}
        assert entries == {
            "20261019_171444/mic.wav": ZIP_STORED,
            "20261019_171444/session.json": ZIP_DEFLATED,
        }
        assert archive.read("20261019_171444/session.json") == b"{}"
