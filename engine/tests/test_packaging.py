"""`packaging/make_installed_env.py`: the `.env` an installed engine starts with;
`packaging/make_source_zip.py`: the engine source for the speaker runtime (phase 56)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import zipfile
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


def _zip_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "make_source_zip", PACKAGING / "make_source_zip.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_source_zip_has_the_package_without_caches(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "vozata" / "__pycache__").mkdir(parents=True)
    (src / "vozata" / "__init__.py").write_text("", encoding="utf-8")
    (src / "vozata" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"")
    (src / "vozata" / "locales").mkdir()
    (src / "vozata" / "locales" / "en.toml").write_text("", encoding="utf-8")

    count = _zip_module().make_zip(src, tmp_path / "out" / "vozata.zip")

    with zipfile.ZipFile(tmp_path / "out" / "vozata.zip") as archive:
        assert sorted(archive.namelist()) == ["vozata/__init__.py", "vozata/locales/en.toml"]
    assert count == 2


def test_the_speaker_child_imports_from_the_source_zip(tmp_path: Path) -> None:
    target = tmp_path / "vozata.zip"
    _zip_module().make_zip(Path(__file__).resolve().parents[1] / "src", target)
    script = "import vozata.diarization.child as c; print(c.__file__)"

    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(target)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert str(target) in result.stdout
