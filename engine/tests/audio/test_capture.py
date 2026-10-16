from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest

from vozata.audio.capture import PA_FLOAT32, PA_INPUT_OVERFLOW, WasapiSource
from vozata.audio.devices import DeviceInfo
from vozata.ports import AudioSource

DEVICE = DeviceInfo(
    id=10, name="Speakers [Loopback]", channels=2, sample_rate=48000, is_loopback=True
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value


class FakeStream:
    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.events: list[str] = []

    def start_stream(self) -> None:
        self.events.append("start")

    def stop_stream(self) -> None:
        self.events.append("stop")

    def close(self) -> None:
        self.events.append("close")


class FakePyAudio:
    def __init__(self) -> None:
        self.open_kwargs: dict[str, Any] = {}
        self.stream: FakeStream | None = None

    def open(self, **kwargs: Any) -> FakeStream:
        self.open_kwargs = kwargs
        self.stream = FakeStream(kwargs["stream_callback"])
        return self.stream


def _stereo_block(frames: int, left: float, right: float) -> bytes:
    block = np.empty((frames, 2), dtype=np.float32)
    block[:, 0], block[:, 1] = left, right
    return block.tobytes()


@pytest.fixture
def pa() -> FakePyAudio:
    return FakePyAudio()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _source(pa: FakePyAudio, clock: FakeClock) -> WasapiSource:
    return WasapiSource(DEVICE, clock, sample_rate=16000, pa=pa)


def _wait_for(condition: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_satisfies_the_audio_source_port(pa: FakePyAudio, clock: FakeClock) -> None:
    assert isinstance(_source(pa, clock), AudioSource)


def test_start_opens_a_float32_stream_with_100_ms_blocks(pa: FakePyAudio, clock: FakeClock) -> None:
    source = _source(pa, clock)

    source.start(lambda samples, at: None)
    source.stop()

    assert pa.open_kwargs | {"stream_callback": None} == {
        "format": PA_FLOAT32,
        "channels": 2,
        "rate": 48000,
        "input": True,
        "input_device_index": 10,
        "frames_per_buffer": 4800,
        "stream_callback": None,
    }
    assert pa.stream is not None
    assert pa.stream.events == ["start", "stop", "close"]


def test_blocks_are_downmixed_resampled_and_timestamped(pa: FakePyAudio, clock: FakeClock) -> None:
    received: list[tuple[np.ndarray, float]] = []
    source = _source(pa, clock)
    source.start(lambda samples, at: received.append((samples, at)))
    assert pa.stream is not None

    for i in range(10):
        clock.value = 0.1 * (i + 1)  # callback fires when the block ends
        pa.stream.callback(_stereo_block(4800, 0.2, 0.6), 4800, {}, 0)
    _wait_for(lambda: len(received) >= 5)
    source.stop()

    total = sum(len(samples) for samples, _ in received)
    assert abs(total - 16000) <= 2  # one second at 16 kHz after the resampler flush
    assert received[0][1] == pytest.approx(0.0)  # block start = callback time - 0.1 s
    middle = np.concatenate([samples for samples, _ in received])[4000:12000]
    assert np.allclose(middle, 0.4, atol=1e-3)  # mean of 0.2 and 0.6


def test_callback_never_blocks_and_counts_overflows(pa: FakePyAudio, clock: FakeClock) -> None:
    source = _source(pa, clock)

    result = source._callback(_stereo_block(10, 0, 0), 10, {}, PA_INPUT_OVERFLOW)

    assert result == (None, 0)
    assert source.overflows == 1


def test_stop_without_start_is_harmless(pa: FakePyAudio, clock: FakeClock) -> None:
    _source(pa, clock).stop()


def test_blocks_still_queued_at_stop_are_delivered(pa: FakePyAudio, clock: FakeClock) -> None:
    received: list[float] = []
    source = _source(pa, clock)
    source._on_samples = lambda samples, at: received.append(at)
    source._stream = FakeStream(None)
    source._callback(_stereo_block(4800, 0.1, 0.1), 4800, {}, 0)
    source._stop.set()

    source._run()

    assert received
    assert source._stream.events == ["stop", "close"]


def test_mono_device_is_not_downmixed(pa: FakePyAudio, clock: FakeClock) -> None:
    mic = DeviceInfo(id=9, name="Mic", channels=1, sample_rate=16000, is_loopback=False)
    received: list[np.ndarray] = []
    source = WasapiSource(mic, clock, sample_rate=16000, pa=pa)
    source._on_samples = lambda samples, at: received.append(samples)

    source._handle(np.full(1600, 0.3, dtype=np.float32).tobytes(), 0.1, 1600)
    source._deliver(source._resampler.resample_chunk(np.zeros(0, np.float32), last=True))

    assert abs(sum(len(samples) for samples in received) - 1600) <= 1


def test_overflows_are_logged_on_stop(
    pa: FakePyAudio, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    source = _source(pa, clock)
    source._callback(b"", 0, {}, PA_INPUT_OVERFLOW)

    source.stop()

    assert "dropped 1 block(s)" in caplog.text


def test_the_native_resampler_is_released_once_capture_ends(
    pa: FakePyAudio, clock: FakeClock
) -> None:
    source = _source(pa, clock)
    source._stream = FakeStream(None)
    source._stop.set()

    source._run()

    assert source._resampler is None  # nothing native survives until interpreter shutdown


def test_a_block_handled_after_capture_ended_raises(pa: FakePyAudio, clock: FakeClock) -> None:
    source = _source(pa, clock)
    source._stream = FakeStream(None)
    source._stop.set()
    source._run()

    with pytest.raises(RuntimeError):
        source._handle(_stereo_block(10, 0, 0), 0.1, 10)


def test_portaudio_calls_go_through_the_given_executor(pa: FakePyAudio, clock: FakeClock) -> None:
    executed: list[str] = []

    def call_audio(function: Any) -> Any:
        executed.append(getattr(function, "__name__", "?"))
        return function()

    source = WasapiSource(DEVICE, clock, sample_rate=16000, pa=pa, call_audio=call_audio)

    source.start(lambda samples, at: None)
    source.stop()

    assert len(executed) == 2  # open, then start_stream
    assert pa.stream is not None and pa.stream.events[:1] == ["start"]
