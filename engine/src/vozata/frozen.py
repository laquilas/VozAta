"""The packaged engine (PyInstaller) as a Python interpreter for its own child processes (phase 51).

The diarizer and the live embedder start `sys.executable -m vozata.diarization.<child>`. In the
packaged build `sys.executable` is `vozata-engine.exe`, so it must run `-m <module>` itself.
"""

from __future__ import annotations

import runpy
import sys
from collections.abc import Callable, Sequence
from typing import Any


def run_module_args(
    argv: Sequence[str],
    *,
    frozen: bool = bool(getattr(sys, "frozen", False)),
    run_module: Callable[..., Any] = runpy.run_module,
) -> bool:
    """Run `argv[0] -m <module> [args]` as `python -m` would and return True; False for any
    other command line (the CLI handles it) or when not frozen (Python runs `-m` itself)."""
    if not frozen or len(argv) < 3 or argv[1] != "-m":
        return False
    module = argv[2]
    sys.argv = [module, *argv[3:]]
    run_module(module, run_name="__main__", alter_sys=True)
    return True
