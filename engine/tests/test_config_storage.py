"""Storage keys (phase 31): `STORAGE_BACKEND`, `DATABASE_PATH` and the OneDrive roots."""

from __future__ import annotations

from pathlib import Path

import pytest

from vozata.config import ConfigError, load_settings, onedrive_roots
from vozata.domain import StorageBackend


def test_storage_defaults_to_sqlite_in_the_output_dir() -> None:
    settings = load_settings(env={"OUTPUT_DIR": "rec"})

    assert settings.storage_backend is StorageBackend.SQLITE
    assert settings.database_path is None
    assert settings.database_file == Path("rec") / "vozata.db"
    assert settings.onedrive_roots == ()


def test_storage_backend_and_database_path_are_read() -> None:
    settings = load_settings(env={"STORAGE_BACKEND": "files", "DATABASE_PATH": "C:/data/v.db"})

    assert settings.storage_backend is StorageBackend.FILES
    assert settings.database_file == Path("C:/data/v.db")


def test_an_unknown_storage_backend_fails() -> None:
    with pytest.raises(ConfigError) as caught:
        load_settings(env={"STORAGE_BACKEND": "postgres"})

    assert caught.value.key == "STORAGE_BACKEND"


def test_onedrive_roots_come_from_the_onedrive_variables_in_any_case() -> None:
    env = {
        "OneDrive": "C:/Users/me/OneDrive",
        "ONEDRIVECOMMERCIAL": "C:/Users/me/OneDrive - Work",
        "onedriveconsumer": "C:/Users/me/OneDrive",  # the same folder again
        "OneDriveOther": "C:/x",
        "OneDriveConsumer": " ",
    }

    roots = (Path("C:/Users/me/OneDrive"), Path("C:/Users/me/OneDrive - Work"))
    assert onedrive_roots(env) == roots
    assert load_settings(env=env).onedrive_roots == roots


def test_onedrive_roots_default_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OneDrive", str(tmp_path / "od"))

    assert tmp_path / "od" in load_settings().onedrive_roots
