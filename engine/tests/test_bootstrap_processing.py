"""Composition of a stopped meeting's processing job (phase 40)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver, FakeTranscriber
from tests.test_session_recover import make_session_folder, segment, write_wav
from vozata import bootstrap
from vozata.config import Settings
from vozata.domain import (
    Channel,
    ConversationLanguage,
    SessionStatus,
    StorageBackend,
    TranscriptionResult,
    Word,
)
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuUsage
from vozata.processing.job import StepKind, run_job_inline
from vozata.storage.files.repository import FileSessionRepository

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
):  # type: ignore[no-untyped-def]
    audio = bootstrap.build_audio_store(settings)
    return bootstrap.build_processing_job(
        settings,
        store,
        audio,
        observer or FakeSessionObserver(),
        session_id,
        repair=repair,
        closed=closed,
        gate_usage=USAGE,
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
