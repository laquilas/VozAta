from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from tests.fakes import FakeAudioSink, FakeSessionObserver, FakeTranscriber, FakeTranscriptSink
from vozata.config import Settings
from vozata.domain import Channel, ConversationLanguage, TranscriptSegment, Word
from vozata.session_pipeline import CapturePipeline, _DeferredTranscriber, _echo_filter
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
        _Sink(log),
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

    pipeline._sink.close = broken  # type: ignore[method-assign]
    pipeline.abandon(closed.set)  # never started: closes at once, nothing was loaded

    assert closed.is_set()
    assert log == ["finalize"]
    assert "sink broke" in caplog.text
