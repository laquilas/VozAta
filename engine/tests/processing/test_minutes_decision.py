"""Minutes skipped at Stop and the 'minutes not generated' marker (phase 64)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeSessionObserver
from tests.session_folders import make_session_folder
from vozata import bootstrap, bootstrap_processing
from vozata.api.payloads import minutes_state
from vozata.config import Settings
from vozata.domain import StorageBackend
from vozata.processing.job import StepKind
from vozata.processing.minutes_decision import BY_USER, NOT_READY, minutes_skip_reason


@pytest.mark.parametrize(
    ("setting", "meta", "ready", "reason"),
    [
        (True, {}, True, None),
        (False, {"generate_minutes": False}, False, None),  # off for every meeting: no marker
        (True, {"generate_minutes": False}, True, BY_USER),
        (True, {"minutes_not_ready": True}, True, NOT_READY),
        (True, {}, False, NOT_READY),
        (True, {"generate_minutes": True}, True, None),
    ],
)
def test_the_skip_rules(
    setting: bool, meta: dict[str, Any], ready: bool, reason: str | None
) -> None:
    assert minutes_skip_reason(setting, meta, lambda: ready) == reason


class Observer(FakeSessionObserver):
    def __init__(self) -> None:
        super().__init__()
        self.skipped: list[str] = []

    def on_minutes_skipped(self, reason: str) -> None:
        self.skipped.append(reason)


def _job(
    tmp_path: Path, meta: dict[str, Any], ready: bool = True
) -> tuple[Any, Any, Observer, str]:
    settings = Settings(
        output_dir=tmp_path / "recordings",
        storage_backend=StorageBackend.FILES,
        stt_provider="fake",
        llm_provider="fake",
    )
    store = bootstrap.build_store(settings)
    session_id = make_session_folder(store)
    store.write_meta(session_id, {**store.read_meta(session_id), **meta})
    observer = Observer()
    job = bootstrap_processing.build_processing_job(
        settings,
        store,
        bootstrap.build_audio_store(settings),
        observer,
        session_id,
        repair=False,
        closed=None,
        gate_usage=bootstrap_processing.GpuUsage(speech=False, speakers=False, llm=False),
        model_ready=lambda: ready,
    )
    return job, store, observer, session_id


def test_a_meeting_whose_option_is_off_is_processed_without_minutes_and_marked(
    tmp_path: Path,
) -> None:
    job, store, observer, session_id = _job(tmp_path, {"generate_minutes": False})

    kinds = [step.kind for step in job.steps]
    assert StepKind.MINUTES not in kinds and StepKind.ACTION_ITEMS not in kinds
    assert store.read_meta(session_id)["minutes_skipped"] == BY_USER
    assert observer.skipped == [BY_USER]


def test_an_unreachable_language_model_skips_the_minutes_as_not_ready(tmp_path: Path) -> None:
    job, store, observer, session_id = _job(tmp_path, {}, ready=False)

    assert StepKind.MINUTES not in [step.kind for step in job.steps]
    assert store.read_meta(session_id)["minutes_skipped"] == NOT_READY
    assert observer.skipped == [NOT_READY]


def test_a_ready_engine_writes_the_minutes_without_a_marker(tmp_path: Path) -> None:
    job, store, observer, session_id = _job(tmp_path, {})

    assert StepKind.MINUTES in [step.kind for step in job.steps]
    assert "minutes_skipped" not in store.read_meta(session_id)
    assert observer.skipped == []


@pytest.mark.parametrize(
    ("has_minutes", "meta", "processing", "state"),
    [
        (True, {"minutes_skipped": "by_user"}, None, "generated"),
        (False, {"minutes_skipped": "not_ready"}, None, "skipped_not_ready"),
        (False, {"minutes_skipped": "by_user"}, {"state": "running"}, "skipped_by_user"),
        (False, {}, {"state": "queued"}, "pending"),
        (False, {"minutes_skipped": "odd"}, None, "none"),
        (False, {}, None, "none"),
    ],
)
def test_the_minutes_state_of_a_meeting(
    has_minutes: bool, meta: dict[str, Any], processing: dict[str, Any] | None, state: str
) -> None:
    assert minutes_state(has_minutes, meta, processing) == state
