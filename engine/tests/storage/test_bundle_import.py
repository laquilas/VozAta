"""`extract_bundle` (phase 39): a meeting ZIP back into a session folder, strictly."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from vozata.storage.bundle_import import BundleError, BundleTooLargeError, extract_bundle

ID = "20261019_171444"


def _zip(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    path = tmp_path / "bundle.zip"
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_the_session_folder_is_unpacked(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {f"{ID}/session.json": b"{}", f"{ID}/mic.wav": b"RIFF"})

    folder = extract_bundle(archive, tmp_path / "out")

    assert folder == tmp_path / "out" / ID
    assert sorted(path.name for path in folder.iterdir()) == ["mic.wav", "session.json"]
    assert (folder / "mic.wav").read_bytes() == b"RIFF"


def test_directory_entries_are_ignored(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {f"{ID}/": b"", f"{ID}/session.json": b"{}"})

    assert extract_bundle(archive, tmp_path / "out").name == ID


@pytest.mark.parametrize(
    "name",
    [
        f"{ID}/../evil.json",
        "../evil.json",
        f"/{ID}/session.json",
        f"{ID}/nested/session.json",
        f"{ID}/notes.txt",
        "not-an-id/session.json",
        "session.json",
    ],
)
def test_anything_but_a_session_folder_is_refused(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path, {f"{ID}/session.json": b"{}", name: b"x"})

    with pytest.raises(BundleError):
        extract_bundle(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "evil.json").exists()


def test_two_session_folders_are_refused(tmp_path: Path) -> None:
    other = "20261019_171445"
    archive = _zip(tmp_path, {f"{ID}/session.json": b"{}", f"{other}/session.json": b"{}"})

    with pytest.raises(BundleError, match="exactly one"):
        extract_bundle(archive, tmp_path / "out")


def test_a_folder_without_metadata_is_refused(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {f"{ID}/mic.wav": b"RIFF"})

    with pytest.raises(BundleError, match="session.json"):
        extract_bundle(archive, tmp_path / "out")


def test_a_file_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"
    archive.write_bytes(b"not a zip")

    with pytest.raises(BundleError, match="ZIP"):
        extract_bundle(archive, tmp_path / "out")


def test_a_zip_that_unpacks_to_too_much_is_refused_before_writing(tmp_path: Path) -> None:
    archive = _zip(tmp_path, {f"{ID}/session.json": b"{}", f"{ID}/mic.wav": bytes(100)})

    with pytest.raises(BundleTooLargeError):
        extract_bundle(archive, tmp_path / "out", max_bytes=50)
    assert not (tmp_path / "out").exists()
