"""Entry point of the packaged engine (`vozata-engine.exe serve`, `--version`, ...)."""

import multiprocessing
import sys

from vozata.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
