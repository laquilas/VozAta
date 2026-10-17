from __future__ import annotations

import logging
import threading

import numpy as np
import pytest

from tests.fakes import FakeEmbedder, FakeTranscriptSink
from vozata.diarization.live import LiveSpeakerTagger
from vozata.diarization.live_sink import AudioHistory, LiveSpeakerSink
from vozata.domain import AudioChunk, Channel, TranscriptSegment

RATE = 10  # samples per second: easy arithmetic


def _chunk(start: float, values: list[float], channel: Channel = Channel.SYSTEM) -> AudioChunk:
    return AudioChunk(channel, start, np.asarray(values, dtype=np.float32))


def _segment(
    start: float, end: float, channel: Channel = Channel.SYSTEM, number: int = 1
) -> TranscriptSegment:
    return TranscriptSegment(
        f"{channel.value}-{number:06d}", channel, channel.value, start, end, "hi", ()
    )


def test_clip_cuts_across_chunks() -> None:
    history = AudioHistory(RATE)
    history.add(_chunk(0.0, list(range(10))))
    history.add(_chunk(1.0, list(range(10, 20))))

    assert history.clip(0.5, 1.3).tolist() == [5, 6, 7, 8, 9, 10, 11, 12]


def test_clip_skips_overlapping_audio_and_gaps() -> None:
    history = AudioHistory(RATE)
    history.add(_chunk(0.0, [1, 2, 3, 4]))
    history.add(_chunk(0.2, [30, 40, 50, 60]))  # overlaps the first chunk's last two samples
    history.add(_chunk(2.0, [9, 9]))

    assert history.clip(0.0, 3.0).tolist() == [1, 2, 3, 4, 50, 60, 9, 9]


def test_clip_outside_the_kept_audio_is_empty() -> None:
    history = AudioHistory(RATE, keep_seconds=1.0)
    history.add(_chunk(0.0, [1] * 10))
    history.add(_chunk(5.0, [2] * 10))  # the first chunk is now older than 1 s

    assert history.clip(0.0, 1.0).size == 0
    assert history.clip(5.0, 6.0).tolist() == [2] * 10


class _Loader:
    """Builds a tagger over `embedder`; waits for `release` when given one."""

    def __init__(self, embedder: FakeEmbedder, release: threading.Event | None = None) -> None:
        self.embedder = embedder
        self.release = release
        self.done = threading.Event()

    def __call__(self) -> LiveSpeakerTagger:
        if self.release is not None:
            self.release.wait(5)
        self.done.set()
        return LiveSpeakerTagger(self.embedder, threshold=0.7)


def test_system_segments_get_live_speakers_in_order_and_mic_passes_through() -> None:
    downstream = FakeTranscriptSink()
    history = AudioHistory(RATE)
    history.add(_chunk(0.0, [0.5] * 60))
    embedder = FakeEmbedder([[1, 0], [0, 1]])
    loader = _Loader(embedder)
    sink = LiveSpeakerSink(downstream, loader, history)
    sink.start()
    assert loader.done.wait(5)

    sink.emit(_segment(0, 2))
    sink.emit(_segment(1, 2, Channel.MIC))
    sink.emit(_segment(2, 4, number=2))
    sink.close()

    assert [segment.speaker_id for segment in downstream.segments] == [
        "system:1",
        "mic",
        "system:2",
    ]
    assert [len(clip) for clip in embedder.calls] == [20, 20]
    assert downstream.closed
    assert embedder.closed


def test_segments_before_the_model_is_ready_keep_system() -> None:
    downstream = FakeTranscriptSink()
    release = threading.Event()
    embedder = FakeEmbedder([[1, 0]])
    loader = _Loader(embedder, release)
    sink = LiveSpeakerSink(downstream, loader, AudioHistory(RATE))
    sink.start()

    sink.emit(_segment(0, 2))
    release.set()
    sink.close()

    assert [segment.speaker_id for segment in downstream.segments] == ["system"]
    assert embedder.calls == []
    assert loader.done.is_set()


def test_a_model_still_loading_at_close_is_released_once_loaded() -> None:
    release = threading.Event()
    embedder = FakeEmbedder()
    loader = _Loader(embedder, release)
    sink = LiveSpeakerSink(FakeTranscriptSink(), loader, AudioHistory(RATE))
    sink.start()

    sink.close()
    release.set()
    sink._loader.join(5)

    assert embedder.closed


def test_a_failed_load_reports_and_segments_keep_system(caplog: pytest.LogCaptureFixture) -> None:
    downstream = FakeTranscriptSink()
    failures: list[Exception] = []

    def load() -> LiveSpeakerTagger:
        raise RuntimeError("no token")

    sink = LiveSpeakerSink(downstream, load, AudioHistory(RATE), on_failed=failures.append)
    with caplog.at_level(logging.WARNING):
        sink.start()
        sink._loader.join(5)
    sink.emit(_segment(0, 2))
    sink.close()

    assert [str(error) for error in failures] == ["no token"]
    assert [segment.speaker_id for segment in downstream.segments] == ["system"]
    assert "no token" in caplog.text


def test_tagging_and_downstream_errors_never_stop_the_worker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Tagger(LiveSpeakerTagger):
        def tag(self, segment: TranscriptSegment, samples: np.ndarray) -> TranscriptSegment:
            raise ValueError("bad clip")

    class _Flaky(FakeTranscriptSink):
        def emit(self, segment: TranscriptSegment) -> None:
            if segment.channel is Channel.MIC:
                raise OSError("disk full")
            super().emit(segment)

    downstream = _Flaky()
    done = threading.Event()

    def load() -> LiveSpeakerTagger:
        done.set()
        return _Tagger(FakeEmbedder(), threshold=0.7)

    sink = LiveSpeakerSink(downstream, load, AudioHistory(RATE))
    sink.start()
    sink._loader.join(5)
    sink.emit(_segment(0, 2, Channel.MIC))
    sink.emit(_segment(2, 4))
    sink.close()

    assert [segment.speaker_id for segment in downstream.segments] == ["system"]
    assert "bad clip" in caplog.text
    assert "disk full" in caplog.text


def test_close_without_start_forwards_inline_and_never_loads() -> None:
    downstream = FakeTranscriptSink()
    loads: list[int] = []

    def load() -> LiveSpeakerTagger:  # pragma: no cover - must not run
        loads.append(1)
        raise AssertionError

    sink = LiveSpeakerSink(downstream, load, AudioHistory(RATE))
    sink.emit(_segment(0, 2))
    sink.close()

    assert [segment.speaker_id for segment in downstream.segments] == ["system"]
    assert downstream.closed
    assert loads == []
