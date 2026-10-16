from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from vozata.api.system_info import GpuInfo, query_gpu


def _runner(stdout: str = "", error: Exception | None = None):  # type: ignore[no-untyped-def]
    calls: list[dict[str, Any]] = []

    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append({"args": args, **kwargs})
        if error is not None:
            raise error
        return SimpleNamespace(stdout=stdout)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_reads_the_first_gpu_name_and_memory() -> None:
    run = _runner("NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6144\nOther, 1024\n")

    info = query_gpu(run)

    assert info == GpuInfo(True, "NVIDIA GeForce RTX 3050 6GB Laptop GPU", 6144)
    [call] = run.calls
    assert call["args"][0] == "nvidia-smi"
    assert call["timeout"] == 2.0


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 2),
        subprocess.CalledProcessError(9, "nvidia-smi"),
    ],
)
def test_missing_slow_or_failing_nvidia_smi_means_no_gpu(error: Exception) -> None:
    assert query_gpu(_runner(error=error)) == GpuInfo(False)


@pytest.mark.parametrize("stdout", ["", "garbage", "GPU, lots"])
def test_unparseable_output_means_no_gpu(stdout: str) -> None:
    assert query_gpu(_runner(stdout)) == GpuInfo(False)
