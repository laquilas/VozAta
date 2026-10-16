from __future__ import annotations

import queue
import threading

import numpy as np
import pytest

from tests.fakes import FakeTranscriptSink
from vozata.domain import AudioChunk, Channel, TranscriptSegment
from vozata.transcription.worker import TranscriptionWorker


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

    def on_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        if chunk.start == self.fail_at:
            raise RuntimeError("CUDA out of memory")
        self.seen.append(chunk.start)
        return [segment(f"{self.channel.value}-{chunk.start:g}")]

    def flush(self) -> list[TranscriptSegment]:
        self.flushed = True
        return [segment(f"{self.channel.value}-flush")]


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
