"""`vozata-engine speakers install | status | remove` (phase 56): the speaker runtime of this PC."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.diarization.models import has_extra
from vozata.diarization.runtime import SpeakerRuntime
from vozata.diarization.runtime_install import Runner, install
from vozata.ports import Localizer

ACTIONS = ("install", "status", "remove")


def run_speakers(
    action: str,
    runtime: SpeakerRuntime,
    console: ConsoleObserver,
    localizer: Localizer,
    *,
    cuda: Callable[[], bool],
    run: Runner | None = None,
    json_output: bool = False,
    remove_tree: Callable[[Path], None] = lambda path: shutil.rmtree(path, ignore_errors=True),
) -> int:
    """`install` builds the runtime (exit 1 when a step fails), `status` says whether speaker
    identification is available, `remove` deletes the runtime. In development the virtualenv's
    `diarization` extra is used instead: `install` and `remove` only say so (exit 2)."""
    t = localizer.t
    if action == "status":
        ready = has_extra(runtime)
        if json_output:
            body = {"ready": ready, "folder": str(runtime.root), **runtime.details()}
            console.say(json.dumps(body))
        elif not runtime.packaged:
            console.say(t("cli.speakers.development"))
        else:
            key = "status_ready" if ready else "status_missing"
            console.say(t(f"cli.speakers.{key}", folder=runtime.root))
        return 0
    if not runtime.packaged:
        console.say(t("cli.speakers.development"))
        return 2
    if action == "remove":
        remove_tree(runtime.root)
        console.say(t("cli.speakers.removed", folder=runtime.root))
        return 0
    ok = install(
        runtime,
        cuda=cuda(),
        run=run or run_process,
        say=lambda key, **params: console.say(t(f"cli.speakers.{key}", **params)),
        remove_tree=remove_tree,
    )
    return 0 if ok else 1


def run_process(argv: list[str], env: Mapping[str, str]) -> int:
    """Run a step with this console: `uv` shows its own download progress."""
    return subprocess.run(argv, env={**os.environ, **env}, check=False).returncode
