"""Run a diarizer in a child process (`diarization.child`), behind the `Diarizer` port.

`torch` (pyannote) and `ctranslate2` (faster-whisper) each bundle CUDA / cuDNN DLLs; loading both
in one Windows process can pick the wrong copy. The child keeps them apart, and its exit releases
every byte of VRAM before the minutes run.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from vozata.config import ConfigError, Settings
from vozata.domain import SpeakerTurn, WhisperDevice
from vozata.ports import DiarizationError

CHILD_MODULE = "vozata.diarization.child"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash under the UI

Runner = Callable[..., subprocess.CompletedProcess[str]]


class SubprocessDiarizer:
    """Sends one request per `diarize()` to a fresh child process; `close()` has nothing to free."""

    def __init__(
        self,
        hf_token: str,
        device: WhisperDevice,
        command: Sequence[str] = (sys.executable, "-m", CHILD_MODULE),
        run: Runner = subprocess.run,
    ) -> None:
        self._token = hf_token
        self._device = device
        self._command = list(command)
        self._run = run

    def diarize(
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        with tempfile.TemporaryDirectory(prefix="vozata-diarize-") as folder:
            output = Path(folder) / "turns.json"
            request = {
                "wav": str(wav),
                "output": str(output),
                "hf_token": self._token,
                "device": self._device.value,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            }
            completed = self._run(
                self._command,
                input=json.dumps(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
                check=False,
            )
            if completed.returncode != 0:
                raise DiarizationError(
                    _last_line(completed.stderr) or f"exit {completed.returncode}"
                )
            try:
                rows = json.loads(output.read_text(encoding="utf-8"))["turns"]
                return [SpeakerTurn(float(s), float(e), int(i)) for s, e, i in rows]
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise DiarizationError(f"unreadable diarizer output: {error}") from error

    def close(self) -> None:
        """Nothing to release: the child process has already exited."""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def pyannote_from_settings(settings: Settings) -> SubprocessDiarizer:
    """The `pyannote` provider; a missing `HF_TOKEN` is a configuration error."""
    if not settings.hf_token:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")
    return SubprocessDiarizer(settings.hf_token, settings.diarization_device)
