"""GPU information for `GET /health` (graceful when there is no NVIDIA GPU or driver)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NVIDIA_SMI = (
    "nvidia-smi",
    "--query-gpu=name,memory.total",
    "--format=csv,noheader,nounits",
)
TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class GpuInfo:
    available: bool
    name: str | None = None
    vram_total_mb: int | None = None


Runner = Callable[..., Any]


def query_gpu(run: Runner = subprocess.run) -> GpuInfo:
    """The first GPU `nvidia-smi` reports; unavailable on any failure or timeout."""
    try:
        result = run(
            list(NVIDIA_SMI),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=True,
        )
        name, memory = result.stdout.strip().splitlines()[0].rsplit(",", 1)
        return GpuInfo(True, name.strip(), int(float(memory.strip())))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return GpuInfo(False)
