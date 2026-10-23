"""Entry point of the packaged engine (`vozata-engine.exe serve`, `--version`, ...)."""

import multiprocessing
import sys

from vozata.frozen import run_module_args

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # `-m vozata.diarization.child`: the pyannote child processes (phase 51), before the CLI loads
    if run_module_args(sys.argv):
        sys.exit(0)
    from vozata.__main__ import main

    sys.exit(main())
