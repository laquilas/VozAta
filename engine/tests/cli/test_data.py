from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from vozata.__main__ import main
from vozata.cli.console import ConsoleObserver
from vozata.cli.data import data_paths, run_data, shared_folder
from vozata.config import Settings
from vozata.labels import SpeakerLabeler


def _settings(tmp_path: Path, database: Path | None = None) -> Settings:
    return Settings(
        output_dir=tmp_path / "home" / "Documents" / "VozAta",
        database_path=database,
        cuda_runtime_dir=tmp_path / "local" / "VozAta" / "cuda",
    )


def _run(
    settings: Settings, action: str, tmp_path: Path, **options: object
) -> tuple[int, list[str]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    code = run_data(
        action,
        settings,
        ConsoleObserver(localizer, SpeakerLabeler(localizer), out),
        localizer,
        home=tmp_path / "home",
        **options,  # type: ignore[arg-type]
    )
    return code, out.getvalue().splitlines()


def _fill(settings: Settings) -> None:
    (settings.output_dir / "live" / "20261112_140724").mkdir(parents=True)
    (settings.output_dir / "live" / "20261112_140724" / "mic.wav").write_bytes(b"RIFF")
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{settings.database_file}{suffix}").write_bytes(b"db")
    (settings.cuda_runtime_dir).mkdir(parents=True)
    (settings.cuda_runtime_dir.parent / "speakers").mkdir()


def test_paths_lists_the_database_and_the_folders(tmp_path: Path) -> None:
    settings = _settings(tmp_path, database=tmp_path / "VozAtaDb" / "vozata.db")

    code, lines = _run(settings, "paths", tmp_path, json_output=True)

    assert code == 0
    listed = json.loads(lines[0])
    assert listed["database"][:2] == [
        str(tmp_path / "VozAtaDb" / "vozata.db"),
        str(tmp_path / "VozAtaDb" / "vozata.db-wal"),
    ]
    assert listed["folders"] == [
        str(settings.output_dir.absolute()),
        str((tmp_path / "local" / "VozAta").absolute()),
    ]
    code, lines = _run(settings, "paths", tmp_path)
    assert lines[0] == f"cli.data.path(path={tmp_path / 'VozAtaDb' / 'vozata.db'})"
    assert len(lines) == 3


def test_erase_needs_yes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _fill(settings)

    code, lines = _run(settings, "erase", tmp_path)

    assert (code, lines) == (2, ["cli.data.confirm"])
    assert settings.database_file.exists()


def test_erase_deletes_the_database_the_recordings_and_the_runtimes(tmp_path: Path) -> None:
    settings = _settings(tmp_path, database=tmp_path / "VozAtaDb" / "vozata.db")
    _fill(settings)

    code, lines = _run(settings, "erase", tmp_path, yes=True)

    assert code == 0
    assert not settings.database_file.exists()
    assert not Path(f"{settings.database_file}-wal").exists()
    assert (tmp_path / "VozAtaDb").exists()  # the database's folder is not VozAta's to delete
    assert not settings.output_dir.exists()
    assert not (tmp_path / "local" / "VozAta").exists()
    assert (tmp_path / "home" / "Documents").exists()
    assert sum(line.startswith("cli.data.removed") for line in lines) == 5


def test_erase_never_deletes_a_shared_folder_and_reports_failures(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "home" / "Documents",
        cuda_runtime_dir=tmp_path / "local" / "VozAta" / "cuda",
    )
    settings.output_dir.mkdir(parents=True)
    settings.database_file.write_bytes(b"db")
    settings.cuda_runtime_dir.mkdir(parents=True)

    def refuse(path: Path) -> None:
        raise PermissionError("in use")

    code, lines = _run(
        settings, "erase", tmp_path, yes=True, remove_tree=refuse, remove_file=refuse
    )

    assert code == 1
    assert settings.output_dir.exists()
    assert f"cli.data.skipped(path={settings.output_dir.absolute()})" in lines
    assert sum(line.startswith("cli.data.failed") for line in lines) == 2


@pytest.mark.parametrize(
    ("relative", "shared"),
    [
        ("home", True),
        ("home/Documents", True),
        ("home/Desktop", True),
        ("home/Documents/VozAta", False),
        ("C-drive/VozAta", False),
    ],
)
def test_shared_folder(tmp_path: Path, relative: str, shared: bool) -> None:
    assert shared_folder(tmp_path / relative, tmp_path / "home") is shared


def test_a_drive_root_and_the_users_folder_are_shared(tmp_path: Path) -> None:
    assert shared_folder(Path(tmp_path.anchor), tmp_path / "home")
    assert shared_folder(Path(tmp_path.anchor) / "VozAta", tmp_path / "home")  # too close to a root
    assert shared_folder(tmp_path, tmp_path / "home")  # the parent of the home folder


def test_data_paths_has_unique_folders(tmp_path: Path) -> None:
    local = tmp_path / "VozAta"
    settings = Settings(output_dir=local, cuda_runtime_dir=local / "cuda")

    assert data_paths(settings).folders == (local.absolute(),)


def test_the_cli_runs_data_paths(tmp_path: Path) -> None:
    out = io.StringIO()
    env = {"OUTPUT_DIR": str(tmp_path / "rec"), "LOCALAPPDATA": str(tmp_path / "local")}

    code = main(["data", "paths", "--json"], stdout=out, env=env)

    assert code == 0
    assert json.loads(out.getvalue())["folders"][0] == str((tmp_path / "rec").absolute())
