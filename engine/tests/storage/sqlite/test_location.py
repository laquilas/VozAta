"""`onedrive_root` (phase 31): is the database in a OneDrive-synced folder?"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vozata.storage.sqlite.location import onedrive_root


def test_a_path_inside_a_root_is_found(tmp_path: Path) -> None:
    roots = (tmp_path / "Other", tmp_path / "OneDrive")

    assert onedrive_root(tmp_path / "OneDrive" / "rec" / "vozata.db", roots) == roots[1]


def test_a_path_outside_every_root_is_not(tmp_path: Path) -> None:
    roots = (tmp_path / "OneDrive",)

    assert onedrive_root(tmp_path / "OneDriveX" / "vozata.db", roots) is None
    assert onedrive_root(tmp_path / "vozata.db", roots) is None
    assert onedrive_root(tmp_path / "vozata.db", ()) is None


def test_a_relative_path_is_resolved_from_the_working_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert onedrive_root(Path("rec/vozata.db"), (tmp_path,)) == tmp_path


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive")
def test_case_does_not_matter_on_windows(tmp_path: Path) -> None:
    root = tmp_path / "OneDrive"

    assert onedrive_root(Path(str(root).upper()) / "vozata.db", (root,)) == root
