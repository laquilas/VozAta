from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vozata.diarization.runtime import SpeakerRuntime
from vozata.diarization.runtime_install import CPU_INDEX, CUDA_INDEX, install


class _Run:
    """Records each command; `fail` names the step (argv[1] or `-c`) that exits 1. The check
    step writes the marker, as the real one does."""

    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[list[str], Mapping[str, str]]] = []

    def __call__(self, argv: list[str], env: Mapping[str, str]) -> int:
        self.calls.append((argv, env))
        label = " ".join(argv[1:3])
        if self.fail and self.fail in label:
            return 1
        if argv[1] == "-c" and len(argv) == 4:
            Path(argv[3]).write_text("{}", encoding="utf-8")
        if argv[1] == "venv":
            python = Path(argv[-1]) / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"")
        return 0


def _runtime(tmp_path: Path) -> SpeakerRuntime:
    return SpeakerRuntime(tmp_path / "speakers", tmp_path / "bundle")


def test_a_fresh_install_runs_every_step_and_marks_the_runtime_ready(tmp_path: Path) -> None:
    runtime, run, said = _runtime(tmp_path), _Run(), []
    removed: list[Path] = []

    ok = install(
        runtime,
        cuda=True,
        run=run,
        say=lambda key, **p: said.append(key),
        remove_tree=removed.append,
    )

    assert ok and runtime.is_ready()
    uv, python = str(runtime.uv), str(runtime.python)
    assert [argv for argv, _ in run.calls] == [
        [uv, "venv", "--python", "3.13", str(runtime.venv)],
        [
            uv,
            "pip",
            "install",
            "--python",
            python,
            "torch==2.11.0",
            "torchaudio==2.11.0",
            "--index-url",
            CUDA_INDEX,
        ],
        [uv, "pip", "install", "--python", python, "pyannote.audio==4.0.7", "torchcodec==0.17.0"],
        [python, "-c", run.calls[3][0][2], str(runtime.marker)],
    ]
    assert said == ["start", "step_python", "step_torch", "step_pyannote", "step_check", "done"]
    assert removed == [runtime.root / "cache"]
    env = run.calls[0][1]
    assert env["UV_PYTHON_INSTALL_DIR"] == str(runtime.root / "python")
    assert env["UV_CACHE_DIR"] == str(runtime.root / "cache")


def test_without_an_nvidia_gpu_the_cpu_torch_is_installed(tmp_path: Path) -> None:
    run = _Run()

    install(_runtime(tmp_path), cuda=False, run=run, say=lambda key, **p: None)

    assert run.calls[1][0][-2:] == ["--index-url", CPU_INDEX]


def test_a_failed_step_stops_and_leaves_no_marker(tmp_path: Path) -> None:
    runtime, run, said = _runtime(tmp_path), _Run(fail="pip install"), []

    ok = install(runtime, cuda=True, run=run, say=lambda key, **p: said.append((key, p)))

    assert not ok and not runtime.is_ready()
    assert len(run.calls) == 2
    assert said[-1] == ("failed", {"step": "step_torch"})


def test_a_failed_check_leaves_no_marker(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    ok = install(runtime, cuda=True, run=_Run(fail="-c import json"), say=lambda key, **p: None)

    assert not ok and not runtime.marker.exists()


def test_a_ready_runtime_that_still_imports_is_kept(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    install(runtime, cuda=True, run=_Run(), say=lambda key, **p: None)
    run, said = _Run(), []

    ok = install(runtime, cuda=True, run=run, say=lambda key, **p: said.append(key))

    assert ok
    assert [argv[1] for argv, _ in run.calls] == ["-c"]
    assert said == ["already_ready"]


def test_a_broken_runtime_is_built_again(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    install(runtime, cuda=True, run=_Run(), say=lambda key, **p: None)
    removed: list[Path] = []
    run = _Run(fail="-c import torch")

    def remove(path: Path) -> None:
        removed.append(path)
        if path == runtime.venv:
            (path / "Scripts" / "python.exe").unlink()
            (path / "Scripts").rmdir()
            path.rmdir()

    ok = install(runtime, cuda=True, run=run, say=lambda key, **p: None, remove_tree=remove)

    assert ok and runtime.is_ready()
    assert removed[0] == runtime.venv
    assert run.calls[1][0][1] == "venv"
