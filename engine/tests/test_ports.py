from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.fakes import (
    FakeAudioMixer,
    FakeAudioReader,
    FakeAudioSink,
    FakeAudioSource,
    FakeDiarizer,
    FakeEmbedder,
    FakeLanguageModel,
    FakeLocalizer,
    FakeSessionObserver,
    FakeTranscriber,
    FakeTranscriptSink,
)
from vozata import ports
from vozata.domain import Channel, SpeakerTurn, TranscriptionResult, TranscriptSegment, Word


@pytest.mark.parametrize(
    ("fake", "port"),
    [
        (FakeAudioSource(), ports.AudioSource),
        (FakeAudioSink(), ports.AudioSink),
        (FakeTranscriber(), ports.Transcriber),
        (FakeTranscriptSink(), ports.TranscriptSink),
        (FakeAudioMixer(), ports.AudioMixer),
        (FakeAudioReader({}), ports.AudioReader),
        (FakeLanguageModel(), ports.LanguageModel),
        (FakeLocalizer(), ports.Localizer),
        (FakeSessionObserver(), ports.SessionObserver),
        (FakeDiarizer(), ports.Diarizer),
        (FakeEmbedder(), ports.SpeakerEmbedder),
    ],
)
def test_fake_satisfies_its_port(fake: object, port: type) -> None:
    assert isinstance(fake, port)


def test_object_missing_a_method_does_not_satisfy_the_port() -> None:
    class HalfTranscriber:
        def transcribe(self, samples, language, hints=None):  # pragma: no cover
            raise NotImplementedError

    assert not isinstance(HalfTranscriber(), ports.Transcriber)


def test_fake_audio_source_delivers_blocks_and_stops() -> None:
    block = np.ones(3, dtype=np.float32)
    source = FakeAudioSource([(block, 0.5)])
    received: list[float] = []

    source.start(lambda samples, at: received.append(at))
    source.stop()

    assert received == [0.5]
    assert source.stopped


def test_fake_audio_sink_records_writes_and_finalize() -> None:
    sink = FakeAudioSink()

    sink.write(np.zeros(2, dtype=np.float32), 1.0)
    sink.finalize(3.0)

    assert [at for _, at in sink.writes] == [1.0]
    assert sink.finalized_at == 3.0


def test_fake_transcriber_returns_queued_results_then_silence() -> None:
    word = Word(text="hi", start=0.0, end=0.2, probability=0.9)
    transcriber = FakeTranscriber([TranscriptionResult(words=(word,), language="en")])
    samples = np.ones(1, dtype=np.float32)

    silent = transcriber.transcribe(np.zeros(1, dtype=np.float32), "en")
    first = transcriber.transcribe(samples, "en")
    second = transcriber.transcribe(samples, "pt", hints="Avalonia")
    transcriber.close()

    assert silent.words == ()  # silence never consumes a scripted result
    assert first.words == (word,)
    assert second == TranscriptionResult(words=(), language="pt")
    assert transcriber.calls[2][2] == "Avalonia"
    assert transcriber.closed


def test_fake_sinks_and_mixer_record_calls() -> None:
    segment = TranscriptSegment("mic-1", Channel.MIC, "mic", 0.0, 1.0, "hi", ())
    sink = FakeTranscriptSink()
    mixer = FakeAudioMixer()

    sink.emit(segment)
    sink.close()
    mixer.mix("reader", "20261015_202358", Path("x.wav"))

    assert sink.segments == [segment]
    assert sink.closed
    assert mixer.calls == [("reader", "20261015_202358", Path("x.wav"))]


def test_fake_language_model_replies_streams_and_reports_availability() -> None:
    model = FakeLanguageModel(["minutes text", "a b"], available=False)

    assert model.generate("sys", "prompt") == "minutes text"
    assert list(model.stream("sys", "again")) == ["a", "b"]
    assert model.generate("sys", "empty") == ""
    assert not model.is_available()
    assert model.releases == 0
    model.release()
    assert model.releases == 1


def test_fake_localizer_echoes_key_and_params() -> None:
    localizer = FakeLocalizer()

    assert localizer.t("labels.mic") == "labels.mic"
    assert localizer.t("labels.user", n=2) == "labels.user(n=2)"


def test_fake_audio_source_push_requires_start() -> None:
    source = FakeAudioSource()

    with pytest.raises(RuntimeError):
        source.push(np.zeros(1, np.float32), 0.0)


def test_fake_session_observer_groups_events_by_name() -> None:
    observer = FakeSessionObserver()

    observer.on_minutes_ready("20261015_202358")
    observer.on_speakers_relabeled("20261015_202358")
    observer.on_error("minutes_failed", "offline")

    assert observer.of("minutes_ready") == [("20261015_202358",)]
    assert observer.of("speakers_relabeled") == [("20261015_202358",)]
    assert observer.of("error") == [("minutes_failed", "offline")]


def test_fake_diarizer_returns_its_turns_records_calls_and_closes(tmp_path: Path) -> None:
    turns = [SpeakerTurn(0.0, 1.5, 0)]
    diarizer = FakeDiarizer(turns)

    assert diarizer.diarize(tmp_path / "system.wav", 2, 3) == turns
    diarizer.close()

    assert diarizer.calls == [(tmp_path / "system.wav", 2, 3)]
    assert diarizer.closed


def test_fake_diarizer_can_fail() -> None:
    diarizer = FakeDiarizer(error=ports.DiarizationError("no token"))

    with pytest.raises(ports.DiarizationError, match="no token"):
        diarizer.diarize(Path("system.wav"), None, None)
