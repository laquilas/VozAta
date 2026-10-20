from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from tests.fakes import FakeAudioSink, FakeSessionObserver, FakeTranscriber, FakeTranscriptSink
from vozata.config import Settings
from vozata.domain import Channel, ConversationLanguage, TranscriptSegment, Word
from vozata.session_live import _DeferredTranscriber, _echo_filter
from vozata.session_pipeline import CapturePipeline
from vozata.transcription.language_lock import LanguageLock


def test_the_deferred_transcriber_refuses_work_before_the_model_is_loaded() -> None:
    deferred = _DeferredTranscriber(FakeTranscriber, FakeSessionObserver(), lambda error: None)

    with pytest.raises(RuntimeError, match="not loaded"):
        deferred.transcribe(np.zeros(4, np.float32), "en")


def test_the_deferred_transcriber_delegates_once_loaded_and_leaves_closing_to_the_session() -> None:
    observer = FakeSessionObserver()
    fake = FakeTranscriber()
    deferred = _DeferredTranscriber(lambda: fake, observer, lambda error: None)

    assert deferred.load()
    deferred.transcribe(np.ones(4, np.float32), "pt", "hint", prompt="context")
    deferred.close()

    assert deferred.loaded is fake
    assert [(language, hints) for _, language, hints in fake.calls] == [("pt", "hint")]
    assert fake.prompts == ["context"]
    assert not fake.closed
    assert observer.of("model_loading") == [(True,), (False,)]


def _said(channel: Channel, text: str) -> TranscriptSegment:
    words = tuple(
        Word(token, 2.0 + i * 0.4, 2.4 + i * 0.4, 0.9) for i, token in enumerate(text.split())
    )
    return TranscriptSegment(
        f"{channel.value}-1", channel, channel.value, words[0].start, words[-1].end, text, words
    )


@pytest.mark.parametrize("live_partials", [True, False])
def test_a_dropped_echo_clears_the_mic_interim_text_when_partials_are_on(
    live_partials: bool,
) -> None:
    observer = FakeSessionObserver()
    sink = FakeTranscriptSink()
    settings = Settings(chunk_seconds=2.0, live_partials=live_partials)
    echo = _echo_filter(settings, sink, observer)

    echo.emit(_said(Channel.SYSTEM, "see you on Friday"))
    echo.emit(_said(Channel.MIC, "see you on Friday"))

    assert [segment.channel for segment in sink.segments] == [Channel.SYSTEM]
    expected = [(Channel.MIC, "mic", 2.0, "")] if live_partials else []
    assert observer.of("partial") == expected


def test_the_echo_filter_uses_the_settings() -> None:
    settings = Settings(chunk_seconds=2.0, echo_similarity=0.6)
    echo = _echo_filter(settings, FakeTranscriptSink(), FakeSessionObserver())

    assert (echo._threshold, echo._hold) == (0.6, 5.0)


class _Writer(FakeAudioSink):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.samples_written = 1600
        self._log = log

    def finalize(self, total_seconds: float) -> None:
        super().finalize(total_seconds)
        self._log.append("finalize")


class _Sink(FakeTranscriptSink):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    def close(self) -> None:
        super().close()
        self._log.append("sink.close")


class _Transcriber(FakeTranscriber):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    def close(self) -> None:
        super().close()
        self._log.append("transcriber.close")


def _pipeline(log: list[str], load: threading.Event) -> CapturePipeline:
    def factory() -> FakeTranscriber:
        assert load.wait(5)
        return _Transcriber(log)

    return CapturePipeline(
        [Channel.MIC],
        lambda channel: _Writer(log),
        lambda: _Sink(log),
        Settings(chunk_seconds=1.0, live_partials=False),
        factory,
        LanguageLock(ConversationLanguage.EN, lambda language: None),
        FakeSessionObserver(),
    )


def test_abandon_returns_at_once_and_closes_everything_once_the_load_ends() -> None:
    log: list[str] = []
    load = threading.Event()
    closed = threading.Event()
    pipeline = _pipeline(log, load)
    pipeline.accept()
    pipeline.start_transcription()
    pipeline.receiver(Channel.MIC)(np.full(1600, 0.1, np.float32), 0.0)

    started = time.monotonic()
    pipeline.abandon(lambda: (log.append("closed"), closed.set()))
    assert time.monotonic() - started < 0.5
    assert not pipeline.accepting
    assert log == []  # the model is still loading
    load.set()

    assert closed.wait(5)
    assert log == ["sink.close", "transcriber.close", "finalize", "closed"]


def test_abandon_closes_and_finalizes_even_when_a_close_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log: list[str] = []
    load = threading.Event()
    load.set()
    closed = threading.Event()
    pipeline = _pipeline(log, load)

    def broken() -> None:
        raise RuntimeError("sink broke")

    pipeline._live.sink.close = broken  # type: ignore[method-assign]
    pipeline.abandon(closed.set)  # never started: closes at once, nothing was loaded

    assert closed.is_set()
    assert log == ["finalize"]
    assert "sink broke" in caplog.text


class _CountingWriter(FakeAudioSink):
    """Counts written samples; paused blocks are written as silence."""

    def __init__(self) -> None:
        super().__init__()
        self.samples_written = 0
        self.paused = False

    def write(self, samples: np.ndarray, at: float) -> None:
        super().write(np.zeros_like(samples) if self.paused else samples, at)
        self.samples_written += len(samples)


class _AudioOnly:
    def __init__(self) -> None:
        self.writers = {Channel.MIC: _CountingWriter(), Channel.SYSTEM: _CountingWriter()}
        self.observer = FakeSessionObserver()
        self.loads: list[str] = []
        self.transcripts: list[str] = []

        def factory() -> FakeTranscriber:
            self.loads.append("transcriber")
            return FakeTranscriber()

        def open_transcript() -> FakeTranscriptSink:
            self.transcripts.append("opened")
            return FakeTranscriptSink()

        self.pipeline = CapturePipeline(
            [Channel.MIC, Channel.SYSTEM],
            self.writers.__getitem__,
            open_transcript,
            Settings(chunk_seconds=1.0, live_partials=True),
            factory,
            LanguageLock(ConversationLanguage.EN, lambda language: None),
            self.observer,
            speaker_embedder=lambda: pytest.fail("no live speakers"),  # type: ignore[arg-type,return-value]
            live=False,
        )
        self.pipeline.accept()


def test_audio_only_pipeline_writes_and_reports_levels_without_transcribing() -> None:
    rig = _AudioOnly()

    rig.pipeline.receiver(Channel.MIC)(np.full(1600, 0.1, np.float32), 0.0)
    rig.pipeline.receiver(Channel.SYSTEM)(np.full(3200, 0.2, np.float32), 0.0)
    rig.pipeline.stop_capture()

    assert rig.writers[Channel.MIC].samples_written == 1600
    assert rig.writers[Channel.SYSTEM].samples_written == 3200
    assert [channel for channel, _ in rig.observer.of("level")] == [Channel.MIC, Channel.SYSTEM]
    assert rig.loads == [] and rig.transcripts == []  # no model, no transcript files
    assert rig.pipeline.transcriber is None
    assert rig.pipeline.echo_dropped is None
    assert rig.observer.of("model_loading") == [] and rig.observer.of("partial") == []
    with pytest.raises(RuntimeError, match="audio only"):
        rig.pipeline.start_transcription()


def test_audio_only_pipeline_pauses_writers() -> None:
    rig = _AudioOnly()
    mic = rig.pipeline.receiver(Channel.MIC)

    rig.pipeline.set_paused(True)
    mic(np.full(1600, 0.1, np.float32), 0.0)
    rig.pipeline.set_paused(False)
    mic(np.full(1600, 0.1, np.float32), 0.1)

    writes = rig.writers[Channel.MIC].writes
    assert [bool(np.any(samples)) for samples, _ in writes] == [False, True]
    assert not rig.writers[Channel.MIC].paused


def test_audio_only_abandon_finalizes_wavs_and_closes_at_once() -> None:
    rig = _AudioOnly()
    rig.pipeline.receiver(Channel.MIC)(np.full(1600, 0.1, np.float32), 0.0)
    rig.pipeline.receiver(Channel.SYSTEM)(np.full(3200, 0.1, np.float32), 0.0)
    caller = threading.current_thread()
    closed_on: list[threading.Thread] = []

    rig.pipeline.abandon(lambda: closed_on.append(threading.current_thread()))

    assert closed_on == [caller]  # synchronously: there is no worker to wait for
    assert not rig.pipeline.accepting
    assert [writer.finalized_at for writer in rig.writers.values()] == [0.2, 0.2]


def test_audio_only_abort_closes_the_writers() -> None:
    rig = _AudioOnly()

    rig.pipeline.abort()

    assert [writer.finalized_at for writer in rig.writers.values()] == [0, 0]
    assert rig.transcripts == []
