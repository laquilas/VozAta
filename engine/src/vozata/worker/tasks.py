"""What the worker offers, and why a task is missing (phase 51): the worker app shows it."""

from __future__ import annotations

from dataclasses import dataclass

MISSING_EXTRA = "missing_extra"  # the speaker runtime is not downloaded / the extra is not installed
MISSING_HF_TOKEN = "missing_hf_token"  # speakers: the pyannote models need a Hugging Face token


@dataclass(frozen=True)
class WorkerTask:
    name: str  # speech | speakers | translation
    available: bool
    reason: str | None = None  # None when available, or when the worker does not know why

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "available": self.available, "reason": self.reason}


def worker_tasks(
    hf_token: str | None, *, translation_extra: bool, diarization_extra: bool
) -> list[WorkerTask]:
    """Speech always; speakers need the `diarization` extra, then `HF_TOKEN`; translation needs
    the `translation` extra."""
    return [
        WorkerTask("speech", True),
        _task("speakers", MISSING_EXTRA if not diarization_extra else _token_reason(hf_token)),
        _task("translation", None if translation_extra else MISSING_EXTRA),
    ]


def offered(tasks: list[WorkerTask]) -> list[str]:
    return [task.name for task in tasks if task.available]


def _task(name: str, reason: str | None) -> WorkerTask:
    return WorkerTask(name, reason is None, reason)


def _token_reason(hf_token: str | None) -> str | None:
    return None if hf_token else MISSING_HF_TOKEN
