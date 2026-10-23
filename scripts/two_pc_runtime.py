"""The thin, hardware- and process-bound parts of `two_pc_check.py` (phase 52): a scratch client
engine and playback on this PC's default output. Covered by the recorded runs, not unit tests."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType

import httpx

ROOT = Path(__file__).resolve().parents[1]
# keys a scratch engine must take from its own `.env`, never from this shell's environment
ISOLATED = (
    "API_HOST",
    "API_PORT",
    "OUTPUT_DIR",
    "DATABASE_PATH",
    "STORAGE_BACKEND",
    "STT_PROVIDER",
    "DIARIZATION_PROVIDER",
    "TRANSLATION_PROVIDER",
    "DIARIZATION_ENABLED",
    "LIVE_DIARIZATION_ENABLED",
    "GENERATE_MINUTES",
    "EXTRACT_ACTION_ITEMS",
    "LIVE_TRANSCRIPTION",
    "WORKER_URL",
    "WORKER_TOKEN",
    "WORKER_ID",
    "WORKER_DISCOVERY_PORT",
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class ScratchEngine:
    """`python -m vozata serve` in `folder` (its `.env` already written), stopped on exit."""

    def __init__(self, folder: Path, port: int) -> None:
        self.folder = folder
        self.url = f"http://127.0.0.1:{port}"
        self._process: subprocess.Popen[bytes] | None = None
        self._log = folder / "engine.log"

    def __enter__(self) -> ScratchEngine:
        env = {key: value for key, value in os.environ.items() if key not in ISOLATED}
        env["PYTHONPATH"] = str(ROOT / "engine" / "src")
        env["PYTHONIOENCODING"] = "utf-8"
        with self._log.open("wb") as log:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "vozata", "serve"],
                cwd=self.folder,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(f"the scratch engine exited; see {self._log}")
            try:
                if httpx.get(f"{self.url}/health", timeout=15).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.__exit__(None, None, None)  # `with` does not call it when `__enter__` raises
        raise RuntimeError(f"the scratch engine did not answer; see {self._log}")

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()  # only the process this script started
            try:
                self._process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._process.kill()


def play(wav: Path) -> None:
    """Play `wav` on this PC's default output and wait for its end (Windows)."""
    command = f"(New-Object Media.SoundPlayer '{wav}').PlaySync()"
    subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True)
