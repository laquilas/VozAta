"""`AudioSource` over a channel of a live recording of the recorder process (phase 61).

The engine no longer opens the devices when the recorder runs: it follows the recorder's files
and feeds what they hold to the usual `CapturePipeline` (writers, chunkers, live transcription).
It starts at frame 0 (or `start_frame`), so the audio recorded before the engine came up is
replayed first, as fast as the disk gives it; then it keeps up with the recording, `poll`
seconds behind at most. `at` is the frame's time on the recording's timeline.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from vozata.domain import Channel
from vozata.recorder.manifest import Manifest, read_manifest
from vozata.recorder.segment_reader import SegmentReader

_log = logging.getLogger(__name__)

POLL_SECONDS = 0.1
BLOCK_SECONDS = 0.5
DRAIN_TIMEOUT = 60.0


class TailingFileSource:
    def __init__(
        self,
        folder: Path,
        channel: Channel,
        sample_rate: int,
        start_frame: int = 0,
        poll: float = POLL_SECONDS,
        block_seconds: float = BLOCK_SECONDS,
        read: Callable[[Path], Manifest] = read_manifest,
        drain_timeout: float = DRAIN_TIMEOUT,
    ) -> None:
        self._folder = folder
        self._channel = channel
        self._rate = sample_rate
        self.position = start_frame  # next frame to deliver
        self._poll = poll
        self._block = max(1, round(block_seconds * sample_rate))
        self._read = read
        self._drain_timeout = drain_timeout
        self._stop = threading.Event()
        self.finished = threading.Event()  # the recording stopped and every frame was delivered
        self._thread: threading.Thread | None = None
        self._manifest: Manifest | None = None

    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        self._manifest = self._read(self._folder)  # fails at once when there is no recording
        self._thread = threading.Thread(
            target=self._run, args=(on_samples,), name=f"tail-{self._channel.value}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Deliver what is left when the recording stopped, then end; at once otherwise."""
        thread = self._thread
        if thread is None:
            return
        manifest = self._fresh_manifest()
        if manifest is not None and not manifest.active:
            self.finished.wait(self._drain_timeout)
        self._stop.set()
        thread.join()
        self._thread = None

    def _run(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        while not self._stop.is_set():
            manifest = self._fresh_manifest() or self._manifest
            if manifest is None:
                self._stop.wait(self._poll)
                continue
            reader = SegmentReader(self._folder, manifest)
            length = reader.length(self._channel)
            if self.position < length:
                frames = reader.frames(
                    self._channel, self.position, min(self._block, length - self.position)
                )
                if len(frames):
                    at = self.position / self._rate
                    self.position += len(frames)
                    on_samples(frames.astype(np.float32) / 32767.0, at)
                    continue
            if not manifest.active:
                self.finished.set()
                return
            self._stop.wait(self._poll)

    def _fresh_manifest(self) -> Manifest | None:
        try:
            self._manifest = self._read(self._folder)
        except (OSError, ValueError):
            _log.debug("recording.json is being replaced; keeping the last one", exc_info=True)
        return self._manifest
