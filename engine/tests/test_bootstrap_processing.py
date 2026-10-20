"""Composition of a stopped meeting's processing job (phase 40)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver, FakeTranscriber
from tests.session_folders import make_session_folder, segment, write_wav
from vozata import bootstrap, bootstrap_processing
from vozata.config import Settings
from vozata.domain import (
    Channel,
    ConversationLanguage,
    SessionStatus,
    StorageBackend,
    TranscriptionResult,
    Word,
)
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.processing.job import StepKind, run_job_inline
from vozata.processing.queue import ProcessingQueue
from vozata.storage.files.repository import FileSessionRepository
from vozata.transcription.shared import SharedTranscriber

USAGE = GpuUsage(speech=True, speakers=False, llm=True)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    overrides.setdefault("storage_backend", StorageBackend.FILES)
    overrides.setdefault("stt_provider", "fake")
    overrides.setdefault("llm_provider", "fake")
    overrides.setdefault("chunk_mode", "fixed")
    overrides.setdefault("chunk_seconds", 1.0)
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


@pytest.fixture
def transcriber(monkeypatch: pytest.MonkeyPatch) -> FakeTranscriber:
    fake = FakeTranscriber(
        [TranscriptionResult(words=(Word("Rest", 0.1, 0.4, 0.9),), language="pt")] * 4
    )
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: fake)
    return fake


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> list[FakeLanguageModel]:
    built: list[FakeLanguageModel] = []

    def build(settings: Settings) -> FakeLanguageModel:
        built.append(FakeLanguageModel(["# Minutes"] * 4))
        return built[-1]

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", build)
    return built


def _job(
    settings: Settings,
    store: FileSessionRepository,
    session_id: str,
    observer: FakeSessionObserver | None = None,
    *,
    repair: bool = False,
    closed: threading.Event | None = None,
    usage: GpuUsage = USAGE,
    shared: SharedTranscriber | None = None,
):  # type: ignore[no-untyped-def]
    audio = bootstrap.build_audio_store(settings)
    return bootstrap_processing.build_processing_job(
        settings,
        store,
        audio,
        observer or FakeSessionObserver(),
        session_id,
        repair=repair,
        closed=closed,
        gate_usage=usage,
        shared=shared,
    )


def test_build_processing_job_steps_and_gpu_flags(tmp_path: Path, models: list) -> None:
    settings = _settings(tmp_path, diarization_enabled=True)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, mic_seconds=2.0, duration_seconds=2.0)

    job = _job(settings, store, session_id)

    kinds = [step.kind for step in job.steps]
    assert kinds == [
        StepKind.TRANSCRIBE,
        StepKind.MIX,
        StepKind.DIARIZE,
        StepKind.MINUTES,
        StepKind.ACTION_ITEMS,
        StepKind.INDEX,
    ]
    assert [step.gpu for step in job.steps] == [True, False, False, True, True, False]
    # mic written to 0.6 s, system to 1.1 s of 2 s: (1.4 + 0.9) / 2 left on average
    assert job.steps[0].weight == pytest.approx(2 + 60 * 1.15 / 2)
    assert [step.weight for step in job.steps[1:]] == [1, 25, 30, 10, 1]
    assert job.session_id == session_id
    assert models == []  # nothing is built before a step runs


@pytest.mark.parametrize(
    ("overrides", "kinds"),
    [
        (
            {"generate_minutes": False},
            [StepKind.REPAIR, StepKind.TRANSCRIBE, StepKind.MIX, StepKind.INDEX],
        ),
        (
            {"extract_action_items": False},
            [StepKind.REPAIR, StepKind.TRANSCRIBE, StepKind.MIX, StepKind.MINUTES, StepKind.INDEX],
        ),
    ],
)
def test_disabled_steps_are_left_out_and_repair_comes_first(
    tmp_path: Path, overrides: dict, kinds: list[StepKind]
) -> None:
    settings = _settings(tmp_path, **overrides)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)

    job = _job(settings, store, session_id, repair=True)

    assert [step.kind for step in job.steps] == kinds
    assert job.steps[0].gpu is False
    assert job.steps[1].weight == 2.0  # no recorded length: nothing to weigh


def test_job_waits_for_abandoned_pipeline_before_transcribing(
    tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(
        store, mic_seconds=2.0, system_seconds=2.0, segments=[], duration_seconds=2.0
    )
    closed = threading.Event()

    def pipeline_closes() -> None:  # the abandoned worker commits its last segments, then closes
        lines = [
            segment("mic-000001", Channel.MIC, 0.0, "Hello.").to_dict(),
            segment("system-000002", Channel.SYSTEM, 0.0, "Hi.").to_dict(),
        ]
        lines[0]["end"] = lines[1]["end"] = 2.0
        text = "".join(json.dumps(line) + "\n" for line in lines)
        store.paths(session_id).transcript_jsonl.write_text(text, encoding="utf-8")
        closed.set()

    threading.Timer(0.2, pipeline_closes).start()

    run_job_inline(_job(settings, store, session_id, closed=closed))

    assert transcriber.calls == []  # resumed after what the live pipeline wrote
    assert [s.segment_id for s in store.load_raw_transcript(session_id)] == [
        "mic-000001",
        "system-000002",
    ]
    assert store.read_meta(session_id)["status"] == "done"


def test_stop_while_model_loading_still_yields_a_full_transcript(
    tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    settings = _settings(
        tmp_path, generate_minutes=False, transcription_language=ConversationLanguage.AUTO
    )
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(  # live wrote nothing: the model was still loading
        store, mic_seconds=1.0, system_seconds=1.0, segments=[], duration_seconds=1.0
    )
    write_wav(store.paths(session_id).wav(Channel.SYSTEM), 1.0, level=0)  # no echo to drop
    observer = FakeSessionObserver()
    closed = threading.Event()
    closed.set()

    run_job_inline(_job(settings, store, session_id, observer, closed=closed))

    texts = [(s.channel, s.text) for s in store.load_raw_transcript(session_id)]
    assert texts == [(Channel.MIC, "Rest")]
    assert {language for _, language, _ in transcriber.calls} == {"pt"}  # the detected language
    assert all(np.any(samples) for samples, _, _ in transcriber.calls)
    meta = store.read_meta(session_id)
    assert meta["status"] == "done" and meta["ended_at"] is not None
    assert observer.of("status") == [(SessionStatus.DONE, 1.0)]


def test_auto_language_detected_while_transcribing_the_rest_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said = TranscriptionResult(words=(Word("Resto", 0.0, 0.95, 0.9),), language="pt")
    transcriber = FakeTranscriber([said] * 4)
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: transcriber)
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, mic_seconds=4.0, segments=[], duration_seconds=4.0)
    write_wav(store.paths(session_id).wav(Channel.SYSTEM), 4.0, level=0)
    meta = store.read_meta(session_id)
    del meta["language"], meta["language_source"]  # auto, not detected live
    store.write_meta(session_id, meta)
    job = _job(settings, store, session_id)

    job.steps[0].run(CancelToken(), lambda fraction: None)

    meta = store.read_meta(session_id)
    assert (meta["language"], meta["language_source"]) == ("pt", "detected")
    assert transcriber.calls[0][1] is None  # detected per window until locked


def test_a_redone_minutes_step_gets_a_fresh_language_model(
    tmp_path: Path, models: list[FakeLanguageModel]
) -> None:
    settings = _settings(tmp_path)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)
    [minutes] = [step for step in _job(settings, store, session_id).steps if step.kind == "minutes"]

    minutes.run(CancelToken(), lambda fraction: None)
    minutes.run(CancelToken(), lambda fraction: None)  # the queue redoes a cancelled step

    used = [model for model in models if model.prompts]
    assert len(used) == 2  # a cancelled model is closed for good: never reused
    assert store.paths(session_id).minutes_md.read_text(encoding="utf-8") == "# Minutes\n"


def test_the_repair_step_repairs_the_stores_and_stores_the_length(tmp_path: Path) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, status="finalizing", mic_seconds=1.5)
    [repair] = [step for step in _job(settings, store, session_id, repair=True).steps][:1]

    repair.run(CancelToken(), lambda fraction: None)

    assert store.read_meta(session_id)["duration_seconds"] == 1.5


@pytest.mark.parametrize("minutes", [False, True])
def test_the_transcribe_step_uses_the_kept_whisper_on_the_gpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minutes: bool
) -> None:
    loads: list[FakeTranscriber] = []

    def load() -> FakeTranscriber:
        loads.append(FakeTranscriber())
        return loads[-1]

    shared = SharedTranscriber(load)
    shared.lease(keep=True).close()  # the live session kept Whisper loaded
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: FakeTranscriber())
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    settings = _settings(tmp_path, generate_minutes=minutes)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, segments=[], duration_seconds=1.0)
    [transcribe] = [s for s in _job(settings, store, session_id, shared=shared).steps][:1]

    transcribe.run(CancelToken(), lambda fraction: None)

    assert len(loads) == 1  # never a second Whisper next to the kept one
    assert loads[0].calls  # it transcribed the rest
    assert shared.loaded is not minutes  # unloaded when minutes follow (VRAM rule)


def test_without_gpu_speech_the_transcribe_step_loads_its_own_model(
    tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    loads: list[FakeTranscriber] = []
    shared = SharedTranscriber(lambda: loads.append(FakeTranscriber()) or loads[-1])
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, segments=[], duration_seconds=1.0)
    cpu = GpuUsage(speech=False, speakers=False, llm=False)
    [transcribe] = [s for s in _job(settings, store, session_id, usage=cpu, shared=shared).steps][
        :1
    ]

    transcribe.run(CancelToken(), lambda fraction: None)

    assert loads == []  # not gated: a live session may be using the shared model on the CPU
    assert transcriber.calls


def test_repair_success_marks_the_session_finalizing_with_a_capture_end(tmp_path: Path) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, status="interrupted", recovery_error="old")  # crashed
    observer = FakeSessionObserver()
    [repair] = [step for step in _job(settings, store, session_id, observer, repair=True).steps][:1]

    repair.run(CancelToken(), lambda fraction: None)

    meta = store.read_meta(session_id)
    assert observer.of("status") == [(SessionStatus.FINALIZING, 1.0)]  # clients see it
    assert meta["status"] == "finalizing"  # a restart now resumes it
    assert meta["capture_ended_at"] is not None
    assert "recovery_error" not in meta


def test_repair_failure_marks_interrupted_and_fails_the_job(
    tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(
        store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    store.paths(session_id).wav(Channel.SYSTEM).write_bytes(b"garbage")
    observer = FakeSessionObserver()
    states: list[str] = []
    queue = ProcessingQueue(GpuGate(), lambda state: states.append(state.state))
    queue.enqueue(_job(settings, store, session_id, observer, repair=True))
    queue.start()

    assert queue.wait_idle(5)
    queue.stop()

    assert states[-1] == "failed"
    assert "done" not in states
    assert transcriber.calls == []  # no later step ran
    meta = store.read_meta(session_id)
    assert meta["status"] == "interrupted"
    assert "RIFF" in meta["recovery_error"]
    assert observer.of("status") == []  # never reported done
    [(code, message)] = observer.of("error")
    assert code == "recovery_failed"
    assert message.startswith(f'Session "{session_id}" could not be recovered (')


def test_resumed_job_transcribes_from_the_last_committed_segment(
    tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    settings = _settings(tmp_path, generate_minutes=False)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(  # committed: mic to 0.6 s, system to 1.1 s; 3 s recorded
        store,
        status="finalizing",
        capture_ended_at="2026-10-15T20:30:00-03:00",
        mic_seconds=3.0,
        system_seconds=3.0,
        duration_seconds=3.0,
    )
    write_wav(store.paths(session_id).wav(Channel.SYSTEM), 3.0, level=0)  # no echo to drop
    transcript = store.paths(session_id).transcript_jsonl
    with transcript.open("a", encoding="utf-8", newline=chr(10)) as file:
        file.write('{"segment_id": "mic-0000')  # the crash cut the last line

    run_job_inline(_job(settings, store, session_id, repair=True))

    assert transcript.with_name("transcript.jsonl.damaged").exists()  # repaired first
    segments = store.load_raw_transcript(session_id)
    assert [s.segment_id for s in segments[:2]] == ["mic-000001", "system-000002"]
    added = segments[2:]
    assert added  # the rest was transcribed
    first = {Channel.MIC: 0.6, Channel.SYSTEM: 1.1}
    assert all(s.start >= first[s.channel] - 1e-6 for s in added)  # nothing before the commit
    assert {s.segment_id for s in added}.isdisjoint({"mic-000001", "system-000002"})
    meta = store.read_meta(session_id)
    assert meta["status"] == "done"


@pytest.mark.parametrize(
    ("kind", "built"),
    [
        (StepKind.MIX, 0),
        (StepKind.DIARIZE, 0),
        (StepKind.MINUTES, 1),
        (StepKind.ACTION_ITEMS, 1),
        (StepKind.INDEX, 0),
    ],
)
def test_each_step_attempt_builds_only_its_model_and_closes_it(
    tmp_path: Path, models: list[FakeLanguageModel], kind: StepKind, built: int
) -> None:
    settings = _settings(tmp_path, diarization_enabled=True)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)
    [step] = [step for step in _job(settings, store, session_id).steps if step.kind == kind]

    step.run(CancelToken(), lambda fraction: None)  # a missing diarizer only reports an error

    assert len(models) == built  # one language model client at most, never two
    assert all(model.closes == 1 for model in models)


def test_the_finished_hook_builds_no_model(tmp_path: Path, models: list) -> None:
    settings = _settings(tmp_path)
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)

    _job(settings, store, session_id).on_finished()

    assert models == []
    assert store.read_meta(session_id)["status"] == "done"


def test_a_cancelled_transcribe_step_keeps_the_shared_whisper_for_the_live_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = CancelToken()
    loads: list[FakeTranscriber] = []

    def load() -> FakeTranscriber:
        token.cancel()  # a live start pre-empts the step while its lease is open
        loads.append(FakeTranscriber())
        return loads[-1]

    shared = SharedTranscriber(load)
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    settings = _settings(tmp_path, generate_minutes=True)  # minutes follow: normally unloaded
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store, segments=[], duration_seconds=1.0)
    [transcribe] = [s for s in _job(settings, store, session_id, shared=shared).steps][:1]

    with pytest.raises(StepCancelled):
        transcribe.run(token, lambda fraction: None)

    [model] = loads
    assert shared.loaded and not model.closed  # never unloaded just before the live lease
