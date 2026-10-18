"""Storage keys (phase 31): `STORAGE_BACKEND`, `DATABASE_PATH` and the OneDrive roots."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vozata import config
from vozata.config import ConfigError, load_settings, onedrive_registry_roots, onedrive_roots
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


def test_onedrive_roots_default_to_the_process_environment_and_the_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OneDrive", str(tmp_path / "work"))
    personal = Path("E:/OneDrive")
    monkeypatch.setattr(
        config, "onedrive_registry_roots", lambda registry=None: (personal, tmp_path / "work")
    )

    assert load_settings().onedrive_roots == (tmp_path / "work", personal)


def test_an_explicit_mapping_does_not_read_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "onedrive_registry_roots", lambda registry=None: (Path("E:/x"),))

    assert load_settings(env={}).onedrive_roots == ()


class _Key:
    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self) -> _Key:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class FakeWinreg:
    """The bits of `winreg` that `onedrive_registry_roots` uses, over a dict of keys."""

    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, accounts: dict[str, dict[str, object]] | None) -> None:
        self.accounts = accounts

    def OpenKey(self, parent: object, name: str) -> _Key:  # noqa: N802 (winreg API)
        if parent == self.HKEY_CURRENT_USER:
            if self.accounts is None or name != r"Software\Microsoft\OneDrive\Accounts":
                raise FileNotFoundError(name)
            return _Key("accounts")
        return _Key(name)

    def EnumKey(self, key: _Key, index: int) -> str:  # noqa: N802
        names = list(self.accounts or {})
        if index >= len(names):
            raise OSError("no more data")
        return names[index]

    def QueryValueEx(self, key: _Key, name: str) -> tuple[object, int]:  # noqa: N802
        values = (self.accounts or {})[key.path]
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1


def test_the_registry_gives_the_folder_of_every_account() -> None:
    registry = FakeWinreg(
        {
            "Personal": {"UserFolder": "E:\\OneDrive"},
            "Business1": {"UserFolder": "C:\\Users\\me\\OneDrive - Work"},
            "Business2": {},  # signed out: no UserFolder
            "Business3": {"UserFolder": "  "},
            "Business4": {"UserFolder": 7},
            "Business5": {"UserFolder": "E:\\OneDrive"},  # the same folder again
        }
    )

    assert onedrive_registry_roots(registry) == (
        Path("E:\\OneDrive"),
        Path("C:\\Users\\me\\OneDrive - Work"),
    )


def test_an_unreadable_registry_gives_no_roots() -> None:
    assert onedrive_registry_roots(FakeWinreg(None)) == ()


def test_there_is_no_registry_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    assert onedrive_registry_roots() == ()
