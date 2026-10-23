"""The speaker embedder in a long-lived child process (`diarization.embed_child`, phase 15).

Like the diarizer (phase 14), torch never shares a process with ctranslate2 (faster-whisper):
both bundle CUDA / cuDNN. Unlike it, the child lives for the whole recording, so each live
segment costs one round trip, not a model load.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from vozata.config import ConfigError, Settings
from vozata.diarization.embed_child import PREFIX
from vozata.diarization.models import EMBEDDING_MODEL, short_name
from vozata.diarization.runtime import SpeakerRuntime, runtime_for
from vozata.domain import ModelKind, WhisperDevice
from vozata.ports import DiarizationError, ModelDownloader

CHILD_MODULE = "vozata.diarization.embed_child"
LOAD_TIMEOUT = 600.0  # the first run downloads the model
EMBED_TIMEOUT = 30.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash under the UI

_log = logging.getLogger(__name__)

Popen = Callable[..., Any]


class SubprocessEmbedder:
    """Starts the child and waits until its model is loaded; `embed()` is one request/reply.

    A child that exits, answers an error or misses `embed_timeout` raises `DiarizationError`
    (the live tagger then turns itself off). `close()` ends the child (killed if it hangs).
    Not thread-safe: one thread embeds.
    """

    def __init__(
        self,
        hf_token: str,
        device: WhisperDevice,
        sample_rate: int,
        command: Sequence[str] = (sys.executable, "-m", CHILD_MODULE),
        popen: Popen = subprocess.Popen,
        load_timeout: float = LOAD_TIMEOUT,
        embed_timeout: float = EMBED_TIMEOUT,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._embed_timeout = embed_timeout
        self._replies: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=20)
        self._process = popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            env={**os.environ, **env} if env else None,  # the speaker runtime (phase 56)
        )
        self._readers = [
            threading.Thread(target=self._read_replies, name="embedder-out", daemon=True),
            threading.Thread(target=self._read_errors, name="embedder-err", daemon=True),
        ]
        for reader in self._readers:
            reader.start()
        try:
            self._send({"hf_token": hf_token, "device": device.value, "sample_rate": sample_rate})
            self._reply(load_timeout)
        except BaseException:
            self.close()
            raise

    def embed(self, samples: np.ndarray) -> np.ndarray:
        data = np.ascontiguousarray(samples, dtype="<f4").tobytes()
        self._send({"samples": base64.b64encode(data).decode("ascii")})
        reply = self._reply(self._embed_timeout)
        try:
            return np.asarray(reply["embedding"], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as error:
            raise DiarizationError(f"unreadable embedder reply: {error}") from error

    def close(self) -> None:
        process = self._process
        with contextlib.suppress(OSError, ValueError):  # a dead child: unsent data is lost
            process.stdin.close()  # EOF: the child releases its model and exits
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for reader in self._readers:
            reader.join(timeout=1)  # each closes its pipe at EOF

    def _send(self, request: dict[str, Any]) -> None:
        try:
            self._process.stdin.write(json.dumps(request) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as error:
            raise DiarizationError(f"the embedder process is gone ({error})") from error

    def _reply(self, timeout: float) -> dict[str, Any]:
        try:
            reply = self._replies.get(timeout=timeout)
        except queue.Empty:
            raise DiarizationError(f"the embedder did not answer within {timeout:g} s") from None
        if reply is None:
            reason = self._stderr[-1] if self._stderr else "no output"
            raise DiarizationError(f"the embedder process exited ({reason})")
        if "error" in reply:
            raise DiarizationError(str(reply["error"]))
        return reply

    def _read_replies(self) -> None:
        for line in self._process.stdout:
            if not line.startswith(PREFIX):
                continue
            try:
                reply = json.loads(line[len(PREFIX) :])
            except ValueError:
                continue
            if isinstance(reply, dict):
                self._replies.put(reply)
        _close(self._process.stdout)
        self._replies.put(None)

    def _read_errors(self) -> None:
        for line in self._process.stderr:
            if line.strip():
                self._stderr.append(line.strip())
                _log.debug("speaker embedder: %s", line.rstrip())
        _close(self._process.stderr)


def _close(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if close is not None:
        close()


def pyannote_embedder_from_settings(
    settings: Settings, downloader: ModelDownloader, runtime: SpeakerRuntime | None = None
) -> SubprocessEmbedder:
    """The `pyannote` live embedder; a missing `HF_TOKEN` is a configuration error. The model
    is downloaded (with progress events, phase 42) before the child starts."""
    if not settings.hf_token:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")
    child = (runtime or runtime_for(settings)).child(CHILD_MODULE)
    downloader.ensure(
        ModelKind.SPEAKERS,
        EMBEDDING_MODEL,
        token=settings.hf_token,
        name=short_name(EMBEDDING_MODEL),
    )
    return SubprocessEmbedder(
        settings.hf_token,
        settings.diarization_device,
        settings.sample_rate,
        child.argv,
        env=child.env,
    )
