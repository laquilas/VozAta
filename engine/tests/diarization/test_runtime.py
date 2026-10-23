from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vozata.config import ConfigError, Settings
from vozata.diarization.runtime import SpeakerRuntime, bundle_dir, runtime_for


def _ready(root: Path, marker: str = '{"torch": "cu128"}') -> None:
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    (root / "ready.json").write_text(marker, encoding="utf-8")


def test_development_children_run_with_this_python(tmp_path: Path) -> None:
    runtime = SpeakerRuntime(tmp_path, None)

    command = runtime.child("vozata.diarization.child")

    assert command.argv == [sys.executable, "-m", "vozata.diarization.child"]
    assert command.env == {}


def test_the_packaged_engine_uses_the_runtime_python_and_its_own_source(tmp_path: Path) -> None:
    root, bundle = tmp_path / "speakers", tmp_path / "engine" / "speakers"
    _ready(root)
    runtime = SpeakerRuntime(root, bundle)

    command = runtime.child("vozata.diarization.embed_child")

    assert command.argv == [
        str(root / "venv/Scripts/python.exe"),
        "-m",
        "vozata.diarization.embed_child",
    ]
    assert command.env == {"PYTHONPATH": str(bundle / "vozata.zip"), "PYTHONNOUSERSITE": "1"}


def test_the_packaged_engine_without_the_runtime_says_how_to_install_it(tmp_path: Path) -> None:
    runtime = SpeakerRuntime(tmp_path / "speakers", tmp_path / "bundle")

    with pytest.raises(ConfigError) as raised:
        runtime.child("vozata.diarization.child")

    assert raised.value.message_key == "speakers_not_installed"


@pytest.mark.parametrize("missing", ["ready.json", "venv/Scripts/python.exe"])
def test_ready_needs_the_marker_and_the_python(tmp_path: Path, missing: str) -> None:
    _ready(tmp_path)
    (tmp_path / missing).unlink()

    assert SpeakerRuntime(tmp_path, tmp_path).is_ready() is False


def test_details_read_the_marker(tmp_path: Path) -> None:
    _ready(tmp_path)

    assert SpeakerRuntime(tmp_path, None).details() == {"torch": "cu128"}


@pytest.mark.parametrize("marker", ["not json", "[1, 2]"])
def test_unreadable_details_are_empty(tmp_path: Path, marker: str) -> None:
    _ready(tmp_path, marker)

    assert SpeakerRuntime(tmp_path, None).details() == {}


def test_tools_live_in_the_bundle_else_the_root(tmp_path: Path) -> None:
    assert SpeakerRuntime(tmp_path, tmp_path / "b").uv == tmp_path / "b" / "uv.exe"
    assert SpeakerRuntime(tmp_path, None).source_zip == tmp_path / "vozata.zip"


def test_bundle_dir_is_next_to_the_packaged_engine(tmp_path: Path) -> None:
    engine = tmp_path / "engine" / "vozata-engine.exe"

    assert bundle_dir(True, str(engine)) == tmp_path / "engine" / "speakers"
    assert bundle_dir(False, str(engine)) is None


def test_runtime_for_reads_the_folder_from_the_settings(tmp_path: Path) -> None:
    runtime = runtime_for(Settings(speakers_runtime_dir=tmp_path), tmp_path / "b")

    assert runtime == SpeakerRuntime(tmp_path, tmp_path / "b")
