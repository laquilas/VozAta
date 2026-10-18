from __future__ import annotations

import logging
from pathlib import Path

import pytest

from vozata.storage import usage
from vozata.storage.usage import clear_directory, database_size, path_size


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


def test_clear_directory_keeps_the_folder(tmp_path: Path) -> None:
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "mixed.wav").write_bytes(b"x" * 7)
    (tmp_path / "loose.wav").write_bytes(b"x" * 3)

    assert clear_directory(tmp_path) == 10
    assert tmp_path.is_dir() and list(tmp_path.iterdir()) == []


def test_clear_directory_of_a_missing_folder(tmp_path: Path) -> None:
    assert clear_directory(tmp_path / "missing") == 0


def test_a_file_in_use_is_skipped_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    locked = tmp_path / "locked.wav"
    locked.write_bytes(b"x" * 4)
    (tmp_path / "free.wav").write_bytes(b"x" * 6)
    unlink = Path.unlink

    def fake_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "locked.wav":
            raise PermissionError("in use")
        unlink(self, missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)

    with caplog.at_level(logging.WARNING):
        freed = clear_directory(tmp_path)

    assert freed == 6
    assert locked.exists()
    assert "locked.wav" in caplog.text


def test_a_file_deleted_while_measuring_counts_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = tmp_path / "gone.wav"

    def stat(self: Path, **kwargs: object) -> object:
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "stat", stat)

    assert usage._size(gone) == 0  # noqa: SLF001
