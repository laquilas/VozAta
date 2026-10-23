from __future__ import annotations

import io
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.speakers import run_process, run_speakers
from vozata.diarization.runtime import SpeakerRuntime
from vozata.labels import SpeakerLabeler


def _speakers(
    action: str,
    runtime: SpeakerRuntime,
    *,
    json_output: bool = False,
    fail: bool = False,
    removed: list[Path] | None = None,
) -> tuple[int, list[str], list[list[str]]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    calls: list[list[str]] = []

    def run(argv: list[str], env: Mapping[str, str]) -> int:
        calls.append(argv)
        if argv[1] == "venv":
            runtime.python.parent.mkdir(parents=True, exist_ok=True)
            runtime.python.write_bytes(b"")
        if argv[1] == "-c" and len(argv) == 4:
            Path(argv[3]).write_text('{"torch": "2.11.0+cu128"}', encoding="utf-8")
        return 1 if fail else 0

    code = run_speakers(
        action,
        runtime,
        ConsoleObserver(localizer, SpeakerLabeler(localizer), out),
        localizer,
        cuda=lambda: True,
        run=run,
        json_output=json_output,
        remove_tree=(removed if removed is not None else []).append,
    )
    return code, out.getvalue().splitlines(), calls


def _packaged(tmp_path: Path) -> SpeakerRuntime:
    return SpeakerRuntime(tmp_path / "speakers", tmp_path / "bundle")


def test_install_prints_each_step_and_exits_0(tmp_path: Path) -> None:
    runtime = _packaged(tmp_path)

    code, lines, calls = _speakers("install", runtime)

    assert code == 0
    assert lines[0] == f"cli.speakers.start(folder={runtime.root},variant=CUDA)"
    assert lines[1:5] == [
        "cli.speakers.step_python",
        "cli.speakers.step_torch",
        "cli.speakers.step_pyannote",
        "cli.speakers.step_check",
    ]
    assert lines[5] == f"cli.speakers.done(folder={runtime.root})"
    assert len(calls) == 4


def test_a_failed_install_exits_1(tmp_path: Path) -> None:
    code, lines, _ = _speakers("install", _packaged(tmp_path), fail=True)

    assert code == 1
    assert lines[-1] == "cli.speakers.failed(step=step_python)"


def test_status_says_whether_the_runtime_is_ready(tmp_path: Path) -> None:
    runtime = _packaged(tmp_path)
    assert _speakers("status", runtime)[1] == [
        f"cli.speakers.status_missing(folder={runtime.root})"
    ]

    _speakers("install", runtime)

    assert _speakers("status", runtime)[1] == [f"cli.speakers.status_ready(folder={runtime.root})"]


def test_status_as_json_carries_the_marker(tmp_path: Path) -> None:
    runtime = _packaged(tmp_path)
    _speakers("install", runtime)

    _, lines, _ = _speakers("status", runtime, json_output=True)

    assert json.loads(lines[0]) == {
        "ready": True,
        "folder": str(runtime.root),
        "torch": "2.11.0+cu128",
    }


def test_remove_deletes_the_runtime_folder(tmp_path: Path) -> None:
    runtime, removed = _packaged(tmp_path), []

    code, lines, _ = _speakers("remove", runtime, removed=removed)

    assert (code, removed) == (0, [runtime.root])
    assert lines == [f"cli.speakers.removed(folder={runtime.root})"]


def test_development_uses_the_virtualenv(tmp_path: Path) -> None:
    runtime, removed = SpeakerRuntime(tmp_path, None), []

    assert _speakers("install", runtime)[:2] == (2, ["cli.speakers.development"])
    assert _speakers("remove", runtime, removed=removed)[0] == 2
    assert _speakers("status", runtime)[1] == ["cli.speakers.development"]
    assert removed == []


def test_run_process_returns_the_exit_code_with_the_added_environment() -> None:
    script = "import os, sys; sys.exit(int(os.environ['VOZATA_TEST_CODE']))"

    assert run_process([sys.executable, "-c", script], {"VOZATA_TEST_CODE": "3"}) == 3
