"""Write the `.env` an installed engine starts with: `engine/.env.example`, recordings in Documents.

usage: python packaging/make_installed_env.py engine/.env.example build/installed.env
"""

from __future__ import annotations

import sys
from pathlib import Path

INSTALLED = {
    # python-dotenv expands ${VAR} from the environment when the engine reads .env
    "OUTPUT_DIR": "${USERPROFILE}/Documents/VozAta",
}


def installed_env(example: str) -> str:
    lines = []
    for line in example.splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={INSTALLED[key]}" if "=" in line and key in INSTALLED else line)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(installed_env(source.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
