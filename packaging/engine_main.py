"""Entry point of the packaged engine (`vozata-engine.exe serve`, `--version`, ...)."""

import multiprocessing
import sys

from vozata.__main__ import main
from vozata.frozen import run_module_args

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if run_module_args(sys.argv):  # `-m vozata.diarization.child`: the pyannote child processes
        sys.exit(0)
    sys.exit(main())
