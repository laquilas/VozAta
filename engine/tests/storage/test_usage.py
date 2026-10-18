from __future__ import annotations

from pathlib import Path

import pytest

from vozata.storage import usage
from vozata.storage.usage import database_size, path_size


def test_path_size_of_a_file_a_folder_and_nothing(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.wav").write_bytes(b"x" * 10)
    (tmp_path / "two.wav").write_bytes(b"x" * 5)

    assert path_size(tmp_path / "two.wav") == 5
    assert path_size(tmp_path) == 15
    assert path_size(tmp_path / "missing") == 0


def test_database_size_counts_the_wal_files(tmp_path: Path) -> None:
    database = tmp_path / "vozata.db"
    database.write_bytes(b"x" * 8)
    (tmp_path / "vozata.db-wal").write_bytes(b"x" * 4)
    (tmp_path / "vozata.db-shm").write_bytes(b"x" * 2)

    assert database_size(database) == 14
    assert database_size(tmp_path / "other.db") == 0


def test_a_file_deleted_while_measuring_counts_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = tmp_path / "gone.wav"

    def stat(self: Path, **kwargs: object) -> object:
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "stat", stat)

    assert usage._size(gone) == 0  # noqa: SLF001
