"""Build the speaker runtime on this PC (phase 56): `vozata-engine speakers install`.

`uv` (shipped next to the packaged engine) creates a Python 3.13 environment — it downloads its
own Python — and installs the pinned torch / pyannote. An import check then writes `ready.json`,
so a half-done install is never taken for a ready one. The versions match the development
environment of the reference machine.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from vozata.diarization.runtime import SpeakerRuntime

PYTHON = "3.13"
TORCH = ("torch==2.11.0", "torchaudio==2.11.0")
PYANNOTE = ("pyannote.audio==4.0.7", "torchcodec==0.17.0")
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# Runs in the new environment: the marker is written only when both packages import.
CHECK = (
    "import json, sys, torch, pyannote.audio; "
    "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps({"
    "'torch': torch.__version__, 'cuda': torch.version.cuda, "
    "'pyannote': pyannote.audio.__version__}))"
)

Runner = Callable[[list[str], Mapping[str, str]], int]  # argv, environment additions -> exit code
Say = Callable[..., None]  # a step key (`cli.speakers.<key>`) and its parameters


def install(
    runtime: SpeakerRuntime,
    *,
    cuda: bool,
    run: Runner,
    say: Say,
    remove_tree: Callable[[Path], None] = lambda path: shutil.rmtree(path, ignore_errors=True),
) -> bool:
    """Build the runtime, or keep it when it is ready and still imports. False when a step
    failed (it was said which); a later run starts that environment over."""
    env = _uv_env(runtime)
    python = str(runtime.python)
    if runtime.is_ready() and run([python, "-c", "import torch, pyannote.audio"], env) == 0:
        say("already_ready", folder=runtime.root)
        return True
    runtime.marker.unlink(missing_ok=True)
    if runtime.venv.exists():
        remove_tree(runtime.venv)
    index = CUDA_INDEX if cuda else CPU_INDEX
    uv = str(runtime.uv)
    steps: list[tuple[str, list[str]]] = [
        ("step_python", [uv, "venv", "--python", PYTHON, str(runtime.venv)]),
        ("step_torch", [uv, "pip", "install", "--python", python, *TORCH, "--index-url", index]),
        ("step_pyannote", [uv, "pip", "install", "--python", python, *PYANNOTE]),
        ("step_check", [python, "-c", CHECK, str(runtime.marker)]),
    ]
    say("start", folder=runtime.root, variant="CUDA" if cuda else "CPU")
    for key, argv in steps:
        say(key)
        if run(argv, env) != 0:
            runtime.marker.unlink(missing_ok=True)
            say("failed", step=key)
            return False
    remove_tree(runtime.root / "cache")
    say("done", folder=runtime.root)
    return True


def _uv_env(runtime: SpeakerRuntime) -> dict[str, str]:
    """Everything `uv` downloads stays in the runtime folder; no user config is read."""
    return {
        "UV_PYTHON_INSTALL_DIR": str(runtime.root / "python"),
        "UV_CACHE_DIR": str(runtime.root / "cache"),
        "UV_PYTHON_PREFERENCE": "only-managed",
        "UV_NO_CONFIG": "1",
        "PYTHONNOUSERSITE": "1",
    }
