"""Entry point of the packaged engine (`vozata-engine.exe serve`, `--version`, ...)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from vozata.__main__ import main

    sys.exit(main())
