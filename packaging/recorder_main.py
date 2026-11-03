"""Entry point of the packaged recorder (`vozata-recorder.exe`, phase 61)."""

import sys

if __name__ == "__main__":
    from vozata.recorder.__main__ import main

    sys.exit(main())
