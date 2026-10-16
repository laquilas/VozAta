from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

import numpy as np
import pytest

from tests.fakes import FakeTranscriptSink
from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.transcription.worker import PartialOptions, TranscriptionWorker


def chunk(channel: Channel, start: float) -> AudioChunk:
    return AudioChunk(channel=channel, start=start, samples=np.zeros(4, dtype=np.float32))


def segment(segment_id: str) -> TranscriptSegment:
    channel = Channel(segment_id.split("-")[0])
    return TranscriptSegment(segment_id, channel, channel.value, 0.0, 1.0, segment_id, ())


class FakeStitcher:
    """Emits one segment per chunk and one on flush; can be told to fail."""

    def __init__(self, channel: Channel, fail_at: float | None = None) -> None:
        self.channel = channel
        self.fail_at = fail_at
        self.seen: list[float] = []
        self.flushed = False
        self.previews: list[AudioChunk | None] = []
        self.preview_texts: list[tuple[float, str] | None] = []

    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        if chunk.start == self.fail_at:
            raise RuntimeError("CUDA out of memory")
        self.seen.append(chunk.start)
        return [segment(f"{self.channel.value}-{chunk.start:g}")]

    def flush(self) -> list[TranscriptSegment]:
        self.flushed = True
        return [segment(f"{self.channel.value}-flush")]

    def partial(self, tail: AudioChunk | None) -> tuple[float, str] | None:
        self.previews.append(tail)
        return self.preview_texts.pop(0) if self.preview_texts else None


@pytest.fixture
def chunks() -> queue.Queue[AudioChunk]:
    return queue.Queue()


def ids(sink: FakeTranscriptSink) -> list[str]:
    return [s.segment_id for s in sink.segments]


def test_routes_chunks_by_channel_and_emits_segments(chunks: queue.Queue[AudioChunk]) -> None:
    mic, system = FakeStitcher(Channel.MIC), FakeStitcher(Channel.SYSTEM)
    sink = FakeTranscriptSink()
    worker = TranscriptionWorker(chunks, {Channel.MIC: mic, Channel.SYSTEM: system}, sink)

    worker.start()
    chunks.put(chunk(Channel.MIC, 0))
    chunks.put(chunk(Channel.SYSTEM, 0))
    worker.stop()

    assert (mic.seen, system.seen) == ([0], [0])
    assert ids(sink)[:2] == ["mic-0", "system-0"]


def test_stop_drains_the_queue_then_flushes_every_stitcher(
    chunks: queue.Queue[AudioChunk],
) -> None:
    mic, system = FakeStitcher(Channel.MIC), FakeStitcher(Channel.SYSTEM)
    sink = FakeTranscriptSink()
    for start in (0, 5, 10):
        chunks.put(chunk(Channel.MIC, start))
    worker = TranscriptionWorker(chunks, {Channel.MIC: mic, Channel.SYSTEM: system}, sink)

    worker.start()
    worker.stop()

    assert mic.seen == [0, 5, 10]
    assert ids(sink) == ["mic-0", "mic-5", "mic-10", "mic-flush", "system-flush"]
    assert chunks.empty()
    assert not sink.closed  # the session owns the sink


def test_a_failing_chunk_is_logged_and_the_worker_continues(
    chunks: queue.Queue[AudioChunk], caplog: pytest.LogCaptureFixture
) -> None:
    mic = FakeStitcher(Channel.MIC, fail_at=5)
    sink = FakeTranscriptSink()
    for start in (0, 5, 10):
        chunks.put(chunk(Channel.MIC, start))
    worker = TranscriptionWorker(chunks, {Channel.MIC: mic}, sink)

    worker.start()
    worker.stop()

    assert mic.seen == [0, 10]
    assert "CUDA out of memory" in caplog.text


def test_failing_flush_is_logged_and_other_stitchers_still_flush(
    chunks: queue.Queue[AudioChunk], caplog: pytest.LogCaptureFixture
) -> None:
    broken, system = FakeStitcher(Channel.MIC), FakeStitcher(Channel.SYSTEM)
    broken.flush = lambda: (_ for _ in ()).throw(RuntimeError("flush failed"))  # type: ignore[method-assign]
    sink = FakeTranscriptSink()
    worker = TranscriptionWorker(chunks, {Channel.MIC: broken, Channel.SYSTEM: system}, sink)

    worker.start()
    worker.stop()

    assert system.flushed
    assert "flush failed" in caplog.text


def test_backlog_beyond_three_chunks_per_channel_warns_once(
    chunks: queue.Queue[AudioChunk], caplog: pytest.LogCaptureFixture
) -> None:
    for start in range(9):
        chunks.put(chunk(Channel.MIC, start))
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: FakeStitcher(Channel.MIC)}, FakeTranscriptSink()
    )

    worker.start()
    worker.stop()

    assert caplog.text.count("slower than real time") == 1


def test_stop_without_start_still_flushes(chunks: queue.Queue[AudioChunk]) -> None:
    mic = FakeStitcher(Channel.MIC)
    worker = TranscriptionWorker(chunks, {Channel.MIC: mic}, FakeTranscriptSink())

    worker.stop()

    assert mic.flushed


def test_load_runs_on_the_worker_thread_before_any_chunk(
    chunks: queue.Queue[AudioChunk], caplog: pytest.LogCaptureFixture
) -> None:
    mic = FakeStitcher(Channel.MIC)
    order: list[str] = []
    loading = threading.Event()
    release = threading.Event()

    def load() -> bool:
        order.append(threading.current_thread().name)
        loading.set()
        release.wait(5)
        return True

    worker = TranscriptionWorker(chunks, {Channel.MIC: mic}, FakeTranscriptSink(), load=load)
    worker.start()
    assert loading.wait(5)
    for start in range(9):  # a backlog while loading is expected, not a warning
        chunks.put(chunk(Channel.MIC, start))
    release.set()
    worker.stop()

    assert order == ["transcription"]
    assert mic.seen == list(range(9))
    assert mic.flushed
    assert "slower than real time" not in caplog.text


def test_a_failed_load_drops_every_chunk_and_skips_the_flush(
    chunks: queue.Queue[AudioChunk],
) -> None:
    mic = FakeStitcher(Channel.MIC)
    sink = FakeTranscriptSink()
    chunks.put(chunk(Channel.MIC, 0))
    worker = TranscriptionWorker(chunks, {Channel.MIC: mic}, sink, load=lambda: False)

    worker.start()
    chunks.put(chunk(Channel.MIC, 5))
    worker.stop()

    assert (mic.seen, mic.flushed, sink.segments) == ([], False, [])
    assert chunks.empty()


def test_stop_without_start_does_not_load_or_transcribe(chunks: queue.Queue[AudioChunk]) -> None:
    mic = FakeStitcher(Channel.MIC)
    loads: list[int] = []
    chunks.put(chunk(Channel.MIC, 0))
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: mic}, FakeTranscriptSink(), load=lambda: bool(loads.append(1))
    )

    worker.stop()

    assert (loads, mic.seen, mic.flushed) == ([], [], False)
    assert chunks.empty()


class Partials:
    """`PartialOptions` with a hand-moved clock; records what the worker emits."""

    def __init__(self, interval: float = 1.5) -> None:
        self.time = 0.0
        self.emitted: list[tuple[Channel, float, str]] = []
        self.snapshots: list[Channel] = []
        self.options = PartialOptions(interval, self.snapshot, self.emit, lambda: self.time)

    def snapshot(self, channel: Channel) -> AudioChunk | None:
        self.snapshots.append(channel)
        return chunk(channel, 99)

    def emit(self, channel: Channel, start: float, text: str) -> None:
        self.emitted.append((channel, start, text))


def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(400):
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met")


def test_partials_run_only_when_no_chunk_is_waiting(chunks: queue.Queue[AudioChunk]) -> None:
    mic = FakeStitcher(Channel.MIC)
    sizes: list[int] = []
    original = mic.partial

    def partial(tail: AudioChunk | None) -> tuple[float, str] | None:
        sizes.append(chunks.qsize())
        return original(tail)

    mic.partial = partial  # type: ignore[method-assign]
    for start in range(5):
        chunks.put(chunk(Channel.MIC, start))
    partials = Partials()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: mic}, FakeTranscriptSink(), partials=partials.options
    )

    worker.start()
    wait_for(lambda: len(sizes) >= 1)
    worker.stop()

    assert mic.seen == [0, 1, 2, 3, 4]
    assert set(sizes) == {0}


def test_partials_respect_the_interval_per_channel_and_send_only_changes(
    chunks: queue.Queue[AudioChunk],
) -> None:
    mic, system = FakeStitcher(Channel.MIC), FakeStitcher(Channel.SYSTEM)
    mic.preview_texts = [(1.0, "Hel"), (1.0, "Hel"), (1.0, "Hello wor")]
    partials = Partials(interval=1.5)
    worker = TranscriptionWorker(
        chunks,
        {Channel.MIC: mic, Channel.SYSTEM: system},
        FakeTranscriptSink(),
        partials=partials.options,
    )

    worker.start()
    wait_for(lambda: len(mic.previews) == 1 and len(system.previews) == 1)
    time.sleep(0.2)  # many idle loops, the clock has not moved
    assert (len(mic.previews), len(system.previews)) == (1, 1)
    for expected in (2, 3):
        partials.time += 1.5
        wait_for(lambda expected=expected: len(mic.previews) == expected)
    worker.stop()

    assert [preview.start for preview in mic.previews if preview] == [99, 99, 99]
    assert partials.emitted[:2] == [(Channel.MIC, 1.0, "Hel"), (Channel.MIC, 1.0, "Hello wor")]


def test_a_shown_partial_is_cleared_when_its_chunk_yields_no_segment(
    chunks: queue.Queue[AudioChunk],
) -> None:
    mic = FakeStitcher(Channel.MIC)
    mic.preview_texts = [(0.0, "uh")]
    mic.on_chunk = lambda chunk: []  # type: ignore[method-assign]  # noise: nothing committed
    partials = Partials()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: mic}, FakeTranscriptSink(), partials=partials.options
    )

    worker.start()
    wait_for(lambda: partials.emitted == [(Channel.MIC, 0.0, "uh")])
    chunks.put(chunk(Channel.MIC, 3))
    wait_for(lambda: len(partials.emitted) == 2)
    worker.stop()

    assert partials.emitted[1] == (Channel.MIC, 3, "")


def test_a_segment_replaces_the_partial_and_stop_clears_what_is_left(
    chunks: queue.Queue[AudioChunk],
) -> None:
    mic, system = FakeStitcher(Channel.MIC), FakeStitcher(Channel.SYSTEM)
    mic.preview_texts = [(0.0, "Bom")]
    system.preview_texts = [(0.0, "Oi")]
    partials = Partials()
    sink = FakeTranscriptSink()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: mic, Channel.SYSTEM: system}, sink, partials=partials.options
    )

    worker.start()
    wait_for(lambda: len(partials.emitted) == 2)
    chunks.put(chunk(Channel.MIC, 0))  # commits "mic-0": the UI replaces the partial
    wait_for(lambda: ids(sink) == ["mic-0"])
    worker.stop()

    assert (Channel.MIC, 0, "") not in partials.emitted
    assert partials.emitted[-1] == (Channel.SYSTEM, 0.0, "")
    assert [entry for entry in partials.emitted if entry[0] is Channel.MIC] == [
        (Channel.MIC, 0.0, "Bom")
    ]


def test_a_failing_partial_is_logged_and_does_not_stop_the_worker(
    chunks: queue.Queue[AudioChunk], caplog: pytest.LogCaptureFixture
) -> None:
    mic = FakeStitcher(Channel.MIC)
    mic.partial = lambda tail: (_ for _ in ()).throw(RuntimeError("CUDA busy"))  # type: ignore[method-assign]
    partials = Partials()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: mic}, FakeTranscriptSink(), partials=partials.options
    )

    worker.start()
    wait_for(lambda: "CUDA busy" in caplog.text)
    chunks.put(chunk(Channel.MIC, 1))
    worker.stop()

    assert mic.seen == [1]


def test_a_preview_round_stops_as_soon_as_a_chunk_is_waiting(
    chunks: queue.Queue[AudioChunk],
) -> None:
    partials = Partials()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: FakeStitcher(Channel.MIC)}, FakeTranscriptSink(),
        partials=partials.options,
    )  # fmt: skip
    chunks.put(chunk(Channel.MIC, 0))

    worker._preview()  # what the idle loop runs

    assert partials.snapshots == []


def test_no_partials_after_a_failed_load(chunks: queue.Queue[AudioChunk]) -> None:
    partials = Partials()
    worker = TranscriptionWorker(
        chunks, {Channel.MIC: FakeStitcher(Channel.MIC)}, FakeTranscriptSink(),
        load=lambda: False, partials=partials.options,
    )  # fmt: skip

    worker.start()
    time.sleep(0.15)
    worker.stop()

    assert partials.snapshots == []
