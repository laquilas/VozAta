from __future__ import annotations

import dataclasses
import threading
import wave
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import (
    FakeAudioSource,
    FakeClock,
    FakeLanguageModel,
    FakeLocalizer,
    FakeSessionObserver,
    FakeSpeechDetector,
    FakeTranscriber,
    minutes_template,
)
from vozata.audio.levels import rms_db
from vozata.audio.vad_chunker import VadChunker
from vozata.config import Settings
from vozata.domain import (
    AudioChunk,
    Channel,
    ConversationLanguage,
    SessionStatus,
    TranscriptionResult,
    Word,
)
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import Diarizer, LanguageModelError, TranscriptSearch
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.session_pipeline import ChunkerFactory
from vozata.storage.session_store import SessionStore

RATE = 16000
BRT = timezone(timedelta(hours=-3))
STARTED = datetime(2026, 10, 15, 20, 23, 58, tzinfo=BRT)
ENDED = datetime(2026, 10, 15, 20, 30, 0, tzinfo=BRT)
SETTINGS = Settings(
    chunk_seconds=1.0, whisper_model="tiny", llm_max_chars=12000, live_partials=False
)


def _voice(seconds: float, level: float = 0.1) -> np.ndarray:
    return np.full(round(seconds * RATE), level, dtype=np.float32)


def _words(*texts: str) -> TranscriptionResult:
    words = tuple(Word(text, 0.1 + i * 0.1, 0.15 + i * 0.1, 0.9) for i, text in enumerate(texts))
    return TranscriptionResult(words=words, language="en")


class _Log:
    """Shared ordered log of side effects across fakes."""

    def __init__(self) -> None:
        self.entries: list[str] = []


class _LoggingTranscriber(FakeTranscriber):
    def __init__(self, log: _Log, results: list[TranscriptionResult] | None = None) -> None:
        super().__init__(results)
        self._log = log

    def close(self) -> None:
        super().close()
        self._log.entries.append("transcriber.close")


class _CheckingMixer:
    """Records the call and checks that both WAVs are already final and equally long."""

    def __init__(self, log: _Log) -> None:
        self._log = log
        self.lengths: tuple[int, int] | None = None

    def mix(self, mic: Path, system: Path, destination: Path) -> None:
        with wave.open(str(mic), "rb") as a, wave.open(str(system), "rb") as b:
            self.lengths = (a.getnframes(), b.getnframes())
        destination.write_bytes(b"mixed")
        self._log.entries.append("mix")


class _LoggingLanguageModel(FakeLanguageModel):
    def __init__(self, log: _Log, replies: list[str], error: Exception | None = None) -> None:
        super().__init__(replies)
        self._log = log
        self._error = error

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self._log.entries.append("llm.generate")
        if self._error is not None:
            raise self._error
        return super().generate(system, prompt, json_schema)


class _Rig:
    def __init__(
        self,
        tmp_path: Path,
        *,
        results: list[TranscriptionResult] | None = None,
        llm_error: Exception | None = None,
        with_minutes: bool = True,
        language: ConversationLanguage = ConversationLanguage.EN,
        mic: FakeAudioSource | None = None,
        system: FakeAudioSource | None = None,
        open_timeout: float = 5.0,
        chunker_factory: ChunkerFactory | None = None,
        load_gate: threading.Event | None = None,
        load_error: Exception | None = None,
        settings: Settings = SETTINGS,
        diarizer_factory: Callable[[], Diarizer] | None = None,
        search_index: TranscriptSearch | None = None,
        vocabulary: tuple[str, ...] = (),
    ) -> None:
        self._load_gate = load_gate
        self._load_error = load_error
        moments = [STARTED, ENDED]
        self.store = SessionStore(
            tmp_path / "recordings", now=lambda: moments.pop(0) if len(moments) > 1 else moments[0]
        )
        self.log = _Log()
        self.clock = FakeClock()
        self.mic = mic or FakeAudioSource()
        self.system = system or FakeAudioSource()
        self.transcriber = _LoggingTranscriber(self.log, results)
        self.mixer = _CheckingMixer(self.log)
        self.llm = _LoggingLanguageModel(self.log, ["# Minutes"], llm_error)
        localizer = FakeLocalizer()
        self.observer = FakeSessionObserver()
        self.session = RecordingSession(
            settings,
            self.store,
            SessionComponents(
                sources={Channel.MIC: self.mic, Channel.SYSTEM: self.system},
                device_names={Channel.MIC: "Headset Mic", Channel.SYSTEM: "Speakers [Loopback]"},
                clock=self.clock,
                transcriber_factory=self._load_transcriber,
                mixer=self.mixer,
                minutes=MinutesGenerator(self.llm, localizer, 12000, minutes_template())
                if with_minutes
                else None,
                localizer=localizer,
                labeler=SpeakerLabeler(localizer),
                release=lambda: self.log.entries.append("release"),
                chunker_factory=chunker_factory,
                diarizer_factory=diarizer_factory,
                search_index=search_index,
                vocabulary=vocabulary,
            ),
            self.observer,
            language,
            open_timeout=open_timeout,
        )

    def _load_transcriber(self) -> FakeTranscriber:
        if self._load_gate is not None:
            assert self._load_gate.wait(5)
        self.log.entries.append("transcriber.load")
        if self._load_error is not None:
            raise self._load_error
        return self.transcriber

    def paths_text(self) -> str:
        paths = self.session.paths
        return paths.transcript_jsonl.read_text(encoding="utf-8") + paths.transcript_md.read_text(
            encoding="utf-8"
        )

    def wav(self, channel: Channel) -> np.ndarray:
        with wave.open(str(self.session.paths.wav(channel)), "rb") as wav:
            return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)


def test_segments_reach_the_observer_and_the_transcript_files(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hello", " world.")])
    rig.session.start()

    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.stop()

    [(segment,)] = rig.observer.of("segment")
    assert (segment.segment_id, segment.text) == ("mic-000001", "Hello world.")
    paths = rig.session.paths
    assert '"segment_id": "mic-000001"' in paths.transcript_jsonl.read_text(encoding="utf-8")
    assert (
        paths.transcript_md.read_text(encoding="utf-8") == "[00:00:00] labels.mic: Hello world.\n"
    )


def _vad_factory(channel: Channel, on_chunk: Callable[[AudioChunk], None]) -> VadChunker:
    detector = FakeSpeechDetector(RATE)
    return VadChunker(
        channel, RATE, on_chunk, detector,
        min_silence=0.6, min_chunk=0.5, max_chunk=15, speech_pad=0.2,
    )  # fmt: skip


def _wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(400):
        if condition():
            return
        threading.Event().wait(0.005)
    raise AssertionError("condition not met")


def test_interim_text_previews_the_phrase_in_progress_then_the_segment_replaces_it(
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(SETTINGS, live_partials=True, partial_interval_seconds=10)
    rig = _Rig(
        tmp_path,
        results=[_words("Hel"), _words("Hello", " there.")],
        chunker_factory=_vad_factory,
        settings=settings,
    )
    rig.session.start()

    rig.mic.push(_voice(2.0), 0.0)  # still speaking: nothing cut yet
    _wait_for(lambda: bool(rig.observer.of("partial")))
    rig.mic.push(_voice(1.0, 0.0), 2.0)  # the pause ends the phrase
    rig.clock.time = 3.0
    rig.session.stop()

    assert rig.observer.of("partial") == [(Channel.MIC, "mic", 0.0, "Hel")]
    [(segment,)] = rig.observer.of("segment")
    assert segment.text == "Hello there."
    audio = [len(samples) / RATE for samples, _, _ in rig.transcriber.calls]
    assert audio[0] == 2.0  # the uncut phrase
    assert len(audio) == 2  # the committed audio was never previewed again
    assert "partial" not in rig.paths_text()


def test_a_chunker_from_the_components_cuts_at_pauses(tmp_path: Path) -> None:
    channels: list[Channel] = []

    def vad(channel: Channel, on_chunk: Callable[[AudioChunk], None]) -> VadChunker:
        channels.append(channel)
        detector = FakeSpeechDetector(RATE)
        return VadChunker(
            channel, RATE, on_chunk, detector,
            min_silence=0.6, min_chunk=0.5, max_chunk=15, speech_pad=0.2,
        )  # fmt: skip

    rig = _Rig(tmp_path, results=[_words("Hi", " there")], chunker_factory=vad)
    rig.session.start()
    rig.mic.push(np.concatenate((_voice(1.0), _voice(1.0, 0.0))), 0.0)
    rig.clock.time = 2.0
    rig.session.stop()

    assert sorted(channels) == sorted([Channel.MIC, Channel.SYSTEM])
    [(segment,)] = rig.observer.of("segment")
    assert segment.text == "Hi there"
    assert len(rig.transcriber.calls) == 1  # the trailing silence never reached the transcriber


def test_recording_starts_before_the_speech_model_has_loaded(tmp_path: Path) -> None:
    gate = threading.Event()
    rig = _Rig(tmp_path, results=[_words("Early", " words.")], load_gate=gate)

    rig.session.start()  # returns while the model is still loading
    assert rig.session.status is SessionStatus.RECORDING
    assert "transcriber.load" not in rig.log.entries
    rig.mic.push(_voice(1.0), 0.0)  # queued: transcribed once the model is ready
    gate.set()
    rig.clock.time = 1.0
    rig.session.stop()

    [(segment,)] = rig.observer.of("segment")
    assert segment.text == "Early words."
    names = [event[0] for event in rig.observer.events if event[0] != "level"]
    assert names[:3] == ["status", "model_loading", "model_loading"]
    assert rig.observer.of("model_loading") == [(True,), (False,)]


def test_a_failed_model_load_reports_an_error_and_still_saves_the_audio(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Lost.")], load_error=RuntimeError("CUDA out of memory"))

    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.stop()

    assert rig.observer.of("error") == [
        ("model_failed", "errors.session.model_failed(reason=CUDA out of memory)")
    ]
    assert rig.observer.of("model_loading") == [(True,), (False,)]
    assert rig.observer.of("segment") == []
    assert rig.transcriber.calls == []
    assert len(rig.wav(Channel.MIC)) == RATE
    assert rig.session.status is SessionStatus.DONE
    assert "transcriber.close" not in rig.log.entries


def test_levels_are_reported_for_every_block(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()

    rig.mic.push(_voice(0.1, 0.5), 0.0)
    rig.system.push(_voice(0.1, 0.0), 0.0)
    rig.session.stop()

    assert rig.observer.of("level") == [
        (Channel.MIC, rms_db(_voice(0.1, 0.5))),
        (Channel.SYSTEM, rms_db(_voice(0.1, 0.0))),
    ]


def test_status_goes_recording_finalizing_done(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()
    rig.clock.time = 2.5

    rig.session.stop()

    assert rig.observer.of("status") == [
        (SessionStatus.RECORDING, 0.0),
        (SessionStatus.FINALIZING, 2.5),
        (SessionStatus.DONE, 2.5),
    ]
    assert rig.session.status is SessionStatus.DONE
    assert rig.mic.started and rig.mic.stopped and rig.system.stopped


def test_pause_drops_chunks_and_writes_silence(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()

    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.pause()
    rig.mic.push(_voice(1.0), 1.0)
    rig.clock.time = 2.0
    rig.session.resume()
    rig.mic.push(_voice(1.0), 2.0)
    rig.clock.time = 3.0
    rig.session.stop()

    mic = rig.wav(Channel.MIC)
    assert len(mic) == 3 * RATE
    assert (
        np.all(mic[:RATE] > 0) and np.all(mic[RATE : 2 * RATE] == 0) and np.all(mic[2 * RATE :] > 0)
    )
    assert len(rig.transcriber.calls) == 2  # the paused second never reached the transcriber
    statuses = [status for status, _ in rig.observer.of("status")]
    assert statuses[:3] == [SessionStatus.RECORDING, SessionStatus.PAUSED, SessionStatus.RECORDING]
    assert rig.store.read_meta(rig.session.id)["pauses"] == [{"start": 1.0, "end": 2.0}]


def test_pause_and_resume_are_ignored_in_the_wrong_state(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()

    rig.session.resume()
    rig.session.pause()
    rig.session.pause()
    rig.session.stop()

    statuses = [status for status, _ in rig.observer.of("status")]
    assert statuses[:3] == [SessionStatus.RECORDING, SessionStatus.PAUSED, SessionStatus.FINALIZING]


def test_stopping_while_paused_closes_the_open_pause(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()
    rig.clock.time = 1.0
    rig.session.pause()
    rig.clock.time = 4.0

    rig.session.stop()

    assert rig.store.read_meta(rig.session.id)["pauses"] == [{"start": 1.0, "end": 4.0}]


def test_stop_order_finalizes_wavs_then_mixes_then_frees_the_gpu_then_writes_minutes(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path, results=[_words("Hi.")])
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)
    rig.system.push(_voice(2.5, 0.0), 0.0)

    rig.session.stop()

    assert "transcriber.load" in rig.log.entries  # on the worker thread, racing "release"
    finalization = [entry for entry in rig.log.entries if entry != "transcriber.load"]
    assert finalization == ["release", "mix", "transcriber.close", "llm.generate"]
    assert rig.mixer.lengths == (int(2.5 * RATE), int(2.5 * RATE))  # padded to the longest
    assert rig.session.paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"
    assert rig.observer.of("minutes_ready") == [(rig.session.id,)]


def test_minutes_failure_keeps_status_done_and_reports_an_error(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hi.")], llm_error=LanguageModelError("offline"))
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert rig.session.status is SessionStatus.DONE
    assert rig.store.read_meta(rig.session.id)["status"] == "done"
    [(code, message)] = rig.observer.of("error")
    assert code == "minutes_failed"
    assert message.startswith("errors.session.minutes_failed(")
    assert "python -m vozata minutes" in message and "offline" in message
    assert not rig.session.paths.minutes_md.exists()
    assert rig.session.paths.transcript_jsonl.exists()


def test_minutes_are_skipped_when_disabled_or_nothing_was_said(tmp_path: Path) -> None:
    disabled = _Rig(tmp_path / "a", results=[_words("Hi.")], with_minutes=False)
    disabled.session.start()
    disabled.mic.push(_voice(1.0), 0.0)
    disabled.session.stop()
    silent = _Rig(tmp_path / "b")
    silent.session.start()
    silent.session.stop()

    for rig in (disabled, silent):
        assert "llm.generate" not in rig.log.entries
        assert not rig.session.paths.minutes_md.exists()
        assert rig.observer.of("error") == []
        assert rig.session.status is SessionStatus.DONE


def test_mixer_failure_is_reported_and_finalization_continues(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hi.")])

    def broken_mix(mic: Path, system: Path, destination: Path) -> None:
        raise ValueError("disk full")

    rig.mixer.mix = broken_mix  # type: ignore[method-assign]
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "mix_failed" and "disk full" in message
    assert rig.transcriber.closed
    assert rig.session.paths.minutes_md.exists()
    assert rig.session.status is SessionStatus.DONE


def test_session_json_matches_the_data_model(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()

    assert rig.store.read_meta(rig.session.id) == {
        "schema_version": 1,
        "id": "20261015_202358",
        "status": "recording",
        "started_at": "2026-10-15T20:23:58-03:00",
        "ended_at": None,
        "language": "en",
        "language_source": "selected",
        "app_language": "en",
        "template": "general",
        "vocabulary": [],
        "devices": {"mic": "Headset Mic", "system": "Speakers [Loopback]"},
        "pauses": [],
        "settings": {
            "CHUNK_MODE": "vad",
            "CHUNK_SECONDS": 1.0,
            "WHISPER_MODEL": "tiny",
            "MIX_MODE": "mono",
        },
    }

    rig.session.stop()

    meta = rig.store.read_meta(rig.session.id)
    assert (meta["status"], meta["ended_at"]) == ("done", "2026-10-15T20:30:00-03:00")
    assert meta["duration_seconds"] == 0.0  # recorded length, not wall time to the end


def test_a_mic_echo_of_the_system_audio_is_dropped_and_counted(tmp_path: Path) -> None:
    echo = _words("Ship", " it", " Friday.")
    rig = _Rig(tmp_path, results=[echo, echo])
    rig.session.start()

    rig.system.push(_voice(1.0), 0.0)
    rig.mic.push(_voice(1.0), 0.0)  # the speakers, heard again by the microphone
    rig.clock.time = 1.0
    rig.session.stop()

    md = rig.session.paths.transcript_md.read_text(encoding="utf-8")
    assert md == "[00:00:00] labels.system: Ship it Friday.\n"
    assert [segment.channel for (segment,) in rig.observer.of("segment")] == [Channel.SYSTEM]
    assert rig.store.read_meta(rig.session.id)["echo_dropped"] == 1


def test_with_echo_dedupe_off_both_copies_are_kept_and_nothing_is_counted(tmp_path: Path) -> None:
    echo = _words("Ship", " it", " Friday.")
    settings = dataclasses.replace(SETTINGS, echo_dedupe_enabled=False)
    rig = _Rig(tmp_path, results=[echo, echo], settings=settings)
    rig.session.start()

    rig.system.push(_voice(1.0), 0.0)
    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.stop()

    assert len(rig.observer.of("segment")) == 2
    assert "echo_dropped" not in rig.store.read_meta(rig.session.id)


def test_auto_language_is_stored_once_detected(tmp_path: Path) -> None:
    speech = TranscriptionResult(words=(Word("Olá.", 0.0, 3.0, 0.9),), language="pt")
    rig = _Rig(tmp_path, results=[speech], language=ConversationLanguage.AUTO)
    rig.session.start()

    assert "language" not in rig.store.read_meta(rig.session.id)

    rig.mic.push(_voice(4.0), 0.0)
    rig.session.stop()

    meta = rig.store.read_meta(rig.session.id)
    assert (meta["language"], meta["language_source"]) == ("pt", "detected")
    assert rig.observer.of("language_detected") == [(ConversationLanguage.PT,)]
    assert rig.transcriber.calls[0][1] is None  # detection on the first window


def test_stop_is_idempotent_and_ignored_before_start(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.stop()
    rig.session.start()

    rig.session.stop()
    rig.session.stop()

    assert [status for status, _ in rig.observer.of("status")].count(SessionStatus.DONE) == 1


def test_start_twice_raises(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()

    with pytest.raises(RuntimeError):
        rig.session.start()

    rig.session.stop()


def test_paths_and_id_before_start_raise(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    with pytest.raises(RuntimeError):
        _ = rig.session.paths


class _HangingSource(FakeAudioSource):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def start(self, on_samples) -> None:  # type: ignore[no-untyped-def]
        self.release.wait(10)


class _FailingSource(FakeAudioSource):
    def start(self, on_samples) -> None:  # type: ignore[no-untyped-def]
        raise OSError("Invalid device")


def test_a_device_that_does_not_open_in_time_fails_the_start_and_cleans_up(
    tmp_path: Path,
) -> None:
    hanging = _HangingSource()
    rig = _Rig(tmp_path, mic=hanging, open_timeout=0.05)
    try:
        with pytest.raises(SessionStartError) as error:
            rig.session.start()
    finally:
        hanging.release.set()

    assert error.value.code == "device_timeout"
    assert str(error.value) == "errors.session.device_timeout(device=Headset Mic,seconds=0.05)"
    assert rig.store.list_sessions() == []
    assert not any((tmp_path / "recordings").iterdir())
    assert "transcriber.load" not in rig.log.entries  # the model loads only once recording
    assert rig.observer.of("status") == []


def test_a_device_that_fails_to_open_fails_the_start_and_stops_opened_sources(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path, system=_FailingSource())

    with pytest.raises(SessionStartError) as error:
        rig.session.start()

    assert error.value.code == "device_failed"
    assert "Invalid device" in str(error.value)
    assert rig.mic.stopped
    assert not any((tmp_path / "recordings").iterdir())


def test_samples_arriving_after_stop_are_ignored(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()
    rig.session.stop()

    rig.mic.push(_voice(1.0), 0.0)

    assert rig.observer.of("level") == []
    assert len(rig.wav(Channel.MIC)) == 0


def test_a_failing_transcriber_close_does_not_stop_finalization(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hi.")])

    def broken_close() -> None:
        raise RuntimeError("CUDA error")

    rig.transcriber.close = broken_close  # type: ignore[method-assign]
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert rig.session.paths.minutes_md.exists()
    assert rig.session.status is SessionStatus.DONE


def test_the_audio_backend_is_released_after_a_failed_start(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, system=_FailingSource())

    with pytest.raises(SessionStartError):
        rig.session.start()

    assert rig.log.entries == ["release"]  # the transcriber was never loaded


def test_a_failing_release_does_not_stop_finalization(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    def broken_release() -> None:
        raise TimeoutError("PortAudio did not answer")

    rig.session._c = dataclasses.replace(rig.session._c, release=broken_release)
    rig.session.start()

    rig.session.stop()

    assert rig.session.status is SessionStatus.DONE


def test_duration_follows_the_session_clock_once_started(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    assert rig.session.duration_seconds == 0.0

    rig.session.start()
    rig.clock.time = 12.5

    assert rig.session.duration_seconds == 12.5
    rig.session.stop()


def test_duration_seconds_is_the_recorded_length_at_capture_stop(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()
    rig.clock.time = 63.25

    rig.session.stop()

    assert rig.store.read_meta(rig.session.id)["duration_seconds"] == 63.25


def test_status_after_capture_reports_the_recorded_length(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.session.start()
    rig.clock.time = 30.0

    def slow_mix(mic: Path, system: Path, destination: Path) -> None:
        rig.clock.time = 75.0  # finalization takes time; the recording does not grow

    rig.mixer.mix = slow_mix  # type: ignore[method-assign]
    rig.session.stop()

    statuses = rig.observer.of("status")
    assert statuses[-2:] == [(SessionStatus.FINALIZING, 30.0), (SessionStatus.DONE, 30.0)]
    assert rig.session.duration_seconds == 30.0


def test_the_vocabulary_is_stored_and_reaches_every_transcription_as_hints(
    tmp_path: Path,
) -> None:
    rig = _Rig(
        tmp_path,
        results=[_words("Hello", " world.")],
        vocabulary=("Jéssica", "Avalonia"),
    )
    rig.session.start()

    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.stop()

    assert rig.store.read_meta(rig.session.id)["vocabulary"] == ["Jéssica", "Avalonia"]
    assert rig.transcriber.calls
    assert {hints for _, _, hints in rig.transcriber.calls} == {"Jéssica, Avalonia"}


def test_the_minutes_at_stop_get_the_session_vocabulary_as_a_glossary(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hello", " world.")], vocabulary=("Jéssica",))
    rig.session.start()

    rig.mic.push(_voice(1.0), 0.0)
    rig.clock.time = 1.0
    rig.session.stop()

    assert "minutes.glossary(terms=Jéssica)" in rig.llm.prompts[0][1]


def test_session_json_gets_a_heartbeat_with_the_length_so_far(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, settings=dataclasses.replace(SETTINGS, autosave_seconds=0.01))
    rig.session.start()
    rig.clock.time = 2.5

    _wait_for(lambda: rig.store.read_meta(rig.session.id).get("duration_seconds") == 2.5)
    meta = rig.store.read_meta(rig.session.id)
    assert meta["status"] == "recording"
    assert meta["last_heartbeat_at"] == "2026-10-15T20:30:00-03:00"

    rig.session.stop()
    assert rig.store.read_meta(rig.session.id)["status"] == "done"
