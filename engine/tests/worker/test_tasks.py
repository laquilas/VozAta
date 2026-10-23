from __future__ import annotations

import pytest

from vozata.worker.tasks import (
    MISSING_EXTRA,
    MISSING_HF_TOKEN,
    WorkerTask,
    offered,
    worker_tasks,
)


def test_a_worker_with_every_extra_and_a_token_offers_every_task() -> None:
    tasks = worker_tasks("hf_x", translation_extra=True, diarization_extra=True)

    assert tasks == [
        WorkerTask("speech", True),
        WorkerTask("speakers", True),
        WorkerTask("translation", True),
    ]


@pytest.mark.parametrize(
    ("token", "extra", "reason"),
    [
        (None, False, MISSING_EXTRA),  # the edition comes first: a token would not help
        ("hf_x", False, MISSING_EXTRA),
        (None, True, MISSING_HF_TOKEN),
        ("", True, MISSING_HF_TOKEN),
    ],
)
def test_speakers_need_the_extra_and_a_hugging_face_token(
    token: str | None, extra: bool, reason: str
) -> None:
    tasks = worker_tasks(token, translation_extra=True, diarization_extra=extra)

    assert tasks[1] == WorkerTask("speakers", False, reason)


def test_translation_needs_its_extra() -> None:
    tasks = worker_tasks("hf_x", translation_extra=False, diarization_extra=True)

    assert tasks[2] == WorkerTask("translation", False, MISSING_EXTRA)


def test_speech_is_always_offered() -> None:
    tasks = worker_tasks(None, translation_extra=False, diarization_extra=False)

    assert tasks[0] == WorkerTask("speech", True)
    assert offered(tasks) == ["speech"]


def test_a_task_as_json() -> None:
    assert WorkerTask("speakers", False, MISSING_HF_TOKEN).to_dict() == {
        "name": "speakers",
        "available": False,
        "reason": "missing_hf_token",
    }
