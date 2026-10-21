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
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from vozata.config import ConfigError, Settings
from vozata.diarization.models import DIARIZATION_MODEL, short_name
from vozata.domain import ModelKind, SpeakerTurn, WhisperDevice
from vozata.ports import DiarizationError, ModelDownloader

CHILD_MODULE = "vozata.diarization.child"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash under the UI

Launcher = Callable[..., subprocess.Popen[str]]


class SubprocessDiarizer:
    """Sends one request per `diarize()` to a fresh child process; `close()` has nothing to free.

    A cancel is final: once cancelled (even before `diarize()` starts) no child is ever spawned.
    """

    def __init__(
        self,
        hf_token: str,
        device: WhisperDevice,
        command: Sequence[str] = (sys.executable, "-m", CHILD_MODULE),
        popen: Launcher = subprocess.Popen,
    ) -> None:
        self._token = hf_token
        self._device = device
        self._command = list(command)
        self._popen = popen
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._active = False

    def diarize(
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        with self._lock:
            if self._cancelled:  # cancelled before it started (e.g. during the model download)
                raise DiarizationError("cancelled")
            self._active = True
        try:
            return self._diarize(wav, min_speakers, max_speakers)
        finally:
            with self._lock:
                self._active = False

    def _diarize(
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
            returncode, stderr = self._run_child(json.dumps(request))
            if self._cancelled:
                raise DiarizationError("cancelled")
            if returncode != 0:
                raise DiarizationError(_last_line(stderr) or f"exit {returncode}")
            try:
                rows = json.loads(output.read_text(encoding="utf-8"))["turns"]
                return [SpeakerTurn(float(s), float(e), int(i)) for s, e, i in rows]
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise DiarizationError(f"unreadable diarizer output: {error}") from error

    def cancel(self) -> None:
        """Stop `diarize` from another thread: it raises, and never spawns if not yet started."""
        with self._lock:
            self._cancelled = True
            if self._process is not None:
                self._process.terminate()

    def _run_child(self, request: str) -> tuple[int, str]:
        with self._lock:
            if self._cancelled:
                raise DiarizationError("cancelled")
            self._process = self._popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
            )
            process = self._process
        try:
            _, stderr = process.communicate(request)
        finally:
            with self._lock:
                self._process = None
        return process.returncode, stderr or ""

    def close(self) -> None:
        """Nothing to release: the child process has already exited."""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def pyannote_from_settings(settings: Settings, downloader: ModelDownloader) -> SubprocessDiarizer:
    """The `pyannote` provider; a missing `HF_TOKEN` is a configuration error.

    The pipeline is downloaded here, with progress events (phase 42): the child then loads it
    from the Hugging Face cache.
    """
    if not settings.hf_token:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")
    downloader.ensure(
        ModelKind.SPEAKERS,
        DIARIZATION_MODEL,
        token=settings.hf_token,
        name=short_name(DIARIZATION_MODEL),
    )
    return SubprocessDiarizer(settings.hf_token, settings.diarization_device)
