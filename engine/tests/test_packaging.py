"""`packaging/make_installed_env.py`: the `.env` an installed engine starts with."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from vozata.config import load_settings

PACKAGING = Path(__file__).resolve().parents[2] / "packaging"
EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "make_installed_env", PACKAGING / "make_installed_env.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_only_the_recordings_folder_changes() -> None:
    example = EXAMPLE.read_text(encoding="utf-8")

    installed = _module().installed_env(example)

    changed = [
        (before, after)
        for before, after in zip(example.splitlines(), installed.splitlines(), strict=True)
        if before != after
    ]
    assert changed == [("OUTPUT_DIR=recordings", "OUTPUT_DIR=${USERPROFILE}/Documents/VozAta")]


def test_the_engine_reads_recordings_into_the_users_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Ana"))
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    env = tmp_path / ".env"
    env.write_text(_module().installed_env(EXAMPLE.read_text(encoding="utf-8")), encoding="utf-8")

    settings = load_settings(env_file=env)

    assert settings.output_dir == Path(f"{tmp_path / 'Ana'}/Documents/VozAta")


def test_package_data_and_the_pyinstaller_spec_ship_every_minutes_template() -> None:
    import fnmatch
    import tomllib

    from vozata.minutes.template_repository import TEMPLATES_DIR

    pyproject = tomllib.loads((EXAMPLE.parent / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["vozata"]
    package = TEMPLATES_DIR.parents[1]
    templates = [path.relative_to(package).as_posix() for path in TEMPLATES_DIR.glob("*.toml")]
    assert templates
    assert all(any(fnmatch.fnmatch(t, p) for p in patterns) for t in templates)
    # The spec collects every data file of the package, so templates are bundled with locales.
    assert 'collect_data_files("vozata")' in (PACKAGING / "engine.spec").read_text(encoding="utf-8")
