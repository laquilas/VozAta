"""WASAPI capture (`AudioSource`): microphone or loopback, delivered as 16 kHz mono float32."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
import soxr

from vozata.audio.devices import DeviceInfo

PA_FLOAT32 = 1  # pyaudiowpatch.paFloat32
PA_INPUT_OVERFLOW = 2  # pyaudiowpatch.paInputOverflow
PA_CONTINUE = 0  # pyaudiowpatch.paContinue
BLOCK_SECONDS = 0.1

_log = logging.getLogger(__name__)


class Clock(Protocol):
    def now(self) -> float: ...


class WasapiSource:
    """Capture one device; `on_samples(samples, at)` runs on a consumer thread.

    The PortAudio callback only timestamps and queues raw blocks (it never blocks). The consumer
    downmixes to mono, resamples with a stateful `soxr.ResampleStream` (no clicks between blocks)
    and reports `at` = session time of the block's first sample.
    """

    def __init__(
        self,
        device: DeviceInfo,
        clock: Clock,
        sample_rate: int,
        pa: Any | None = None,
        call_audio: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> None:
        """`call_audio` runs PortAudio calls (open, start) on the thread that owns `pa`."""
        self._device = device
        self._call_audio = call_audio or (lambda function: function())
        self._clock = clock
        self._pa = pa
        self._owns_pa = pa is None
        self._resampler: soxr.ResampleStream | None = soxr.ResampleStream(
            device.sample_rate, sample_rate, 1, dtype="float32"
        )
        self._blocks: queue.Queue[tuple[bytes, float, int]] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: Any = None
        self._on_samples: Callable[[np.ndarray, float], None] = lambda samples, at: None
        self._next_at = 0.0
        self.overflows = 0

    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        self._on_samples = on_samples
        if self._pa is None:  # pragma: no cover - hardware
            import pyaudiowpatch

            self._pa = pyaudiowpatch.PyAudio()
        pa = self._pa
        self._stream = self._call_audio(
            lambda: pa.open(
                format=PA_FLOAT32,
                channels=self._device.channels,
                rate=self._device.sample_rate,
                input=True,
                input_device_index=self._device.id,
                frames_per_buffer=round(self._device.sample_rate * BLOCK_SECONDS),
                stream_callback=self._callback,
            )
        )
        self._thread = threading.Thread(target=self._run, name=f"capture-{self._device.id}")
        self._call_audio(self._stream.start_stream)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if self._owns_pa and self._pa is not None:  # pragma: no cover - hardware
            self._pa.terminate()
            self._pa = None
        if self.overflows:
            _log.warning("Device %s dropped %d block(s)", self._device.id, self.overflows)

    def _callback(self, in_data: bytes, frame_count: int, time_info: Any, status: int) -> tuple:
        if status & PA_INPUT_OVERFLOW:
            self.overflows += 1
        self._blocks.put((in_data, self._clock.now(), frame_count))
        return (None, PA_CONTINUE)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self._handle(*self._blocks.get(timeout=0.05))
                except queue.Empty:
                    continue
        finally:
            self._stream.stop_stream()
            self._stream.close()
            while not self._blocks.empty():
                self._handle(*self._blocks.get())
            self._deliver(self._resample(np.zeros(0, np.float32), last=True))
            self._resampler = None  # a native object alive at exit makes nanobind report leaks

    def _handle(self, raw: bytes, captured_at: float, frame_count: int) -> None:
        self._next_at = captured_at - frame_count / self._device.sample_rate
        mono = np.frombuffer(raw, dtype=np.float32)
        if self._device.channels > 1:
            mono = mono.reshape(-1, self._device.channels).mean(axis=1)
        self._deliver(self._resample(mono))

    def _resample(self, samples: np.ndarray, last: bool = False) -> np.ndarray:
        if self._resampler is None:
            raise RuntimeError("WasapiSource was stopped")
        return self._resampler.resample_chunk(samples, last=last)

    def _deliver(self, samples: np.ndarray) -> None:
        if len(samples):
            self._on_samples(samples, self._next_at)
