"""`vozata-engine cuda install | status | remove` (phase 58): the CUDA libraries of this PC."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer
from vozata.transcription.cuda_runtime import CudaRuntime, install

ACTIONS = ("install", "status", "remove")
TIMEOUT = httpx.Timeout(60.0, connect=20.0)  # per read: the wheels are ~0.5-0.7 GB each


def run_cuda(
    action: str,
    runtime: CudaRuntime,
    console: ConsoleObserver,
    localizer: Localizer,
    *,
    client: Callable[[], httpx.Client] = lambda: httpx.Client(
        timeout=TIMEOUT, follow_redirects=True
    ),
    json_output: bool = False,
    remove_tree: Callable[[Path], None] = lambda path: shutil.rmtree(path, ignore_errors=True),
) -> int:
    """`install` downloads the libraries (exit 1 on a failure), `status` says whether they are
    here, `remove` deletes them."""
    t = localizer.t
    if action == "status":
        ready = runtime.is_ready()
        if json_output:
            console.say(
                json.dumps({"ready": ready, "folder": str(runtime.root), **runtime.details()})
            )
        else:
            key = "status_ready" if ready else "status_missing"
            console.say(t(f"cli.cuda.{key}", folder=runtime.root))
        return 0
    if action == "remove":
        remove_tree(runtime.root)
        console.say(t("cli.cuda.removed", folder=runtime.root))
        return 0
    with client() as http:
        ok = install(
            runtime, http, lambda key, **params: console.say(t(f"cli.cuda.{key}", **params))
        )
    return 0 if ok else 1
