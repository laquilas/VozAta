from __future__ import annotations

import io
import json
from pathlib import Path

import httpx

from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.cuda import run_cuda
from vozata.labels import SpeakerLabeler
from vozata.transcription.cuda_runtime import CudaRuntime


def _cuda(
    action: str,
    runtime: CudaRuntime,
    *,
    json_output: bool = False,
    status: int = 404,
    removed: list[Path] | None = None,
) -> tuple[int, list[str]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    code = run_cuda(
        action,
        runtime,
        ConsoleObserver(localizer, SpeakerLabeler(localizer), out),
        localizer,
        client=lambda: httpx.Client(transport=transport),
        json_output=json_output,
        remove_tree=(removed if removed is not None else []).append,
    )
    return code, out.getvalue().splitlines()


def test_status_says_whether_the_libraries_are_here(tmp_path: Path) -> None:
    runtime = CudaRuntime(tmp_path)
    assert _cuda("status", runtime)[1] == [f"cli.cuda.status_missing(folder={tmp_path})"]

    runtime.marker.write_text('{"nvidia-cudnn-cu12": "9"}', encoding="utf-8")

    assert _cuda("status", runtime)[1] == [f"cli.cuda.status_ready(folder={tmp_path})"]
    body = json.loads(_cuda("status", runtime, json_output=True)[1][0])
    assert body == {"ready": True, "folder": str(tmp_path), "nvidia-cudnn-cu12": "9"}


def test_a_failed_install_exits_1(tmp_path: Path) -> None:
    code, lines = _cuda("install", CudaRuntime(tmp_path / "cuda"))

    assert code == 1
    assert lines[0] == f"cli.cuda.start(folder={tmp_path / 'cuda'})"
    assert lines[-1].startswith("cli.cuda.failed(reason=")


def test_install_of_a_ready_runtime_exits_0(tmp_path: Path) -> None:
    runtime = CudaRuntime(tmp_path)
    runtime.marker.write_text("{}", encoding="utf-8")

    assert _cuda("install", runtime) == (0, [f"cli.cuda.already_ready(folder={tmp_path})"])


def test_remove_deletes_the_folder(tmp_path: Path) -> None:
    removed: list[Path] = []

    code, lines = _cuda("remove", CudaRuntime(tmp_path), removed=removed)

    assert (code, removed, lines) == (0, [tmp_path], [f"cli.cuda.removed(folder={tmp_path})"])
