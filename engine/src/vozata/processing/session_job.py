"""The processing job of one stopped meeting (phase 40): what Stop no longer does inline.

Steps, in order: `repair` (after a crash only), `transcribe` (the rest of the meeting from its
stored audio), `mix`, `diarize`, `minutes`, `action_items`, `index`; `on_finished` stamps the
meeting `done`. The WAVs are finalized by the abandoned live pipeline (or repaired) before the
job starts, so `mix` is the whole "finalize" part. Every step builds what it uses when it runs:
a cancelled step is redone by the queue with a fresh language model / diarizer, because a
cancelled one is closed for good.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from vozata.ports import SessionRepository
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuUsage
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.session_finisher import SessionFinisher
from vozata.transcription.offline import OfflineTranscription
from vozata.transcription.offline_feed import CHANNELS
from vozata.transcription.resume import resume_points

Progress = Callable[[float], None]

MIX_WEIGHT = 1.0
DIARIZE_WEIGHT = 25.0
MINUTES_WEIGHT = 30.0
ACTION_ITEMS_WEIGHT = 10.0
INDEX_WEIGHT = 1.0
REPAIR_WEIGHT = 1.0


@dataclass(frozen=True)
class JobParts:
    """How a meeting is finished; `finisher` and `transcription` are called once per attempt.

    `finisher(models)` builds the language model and diarizer only when `models` is true (the
    `mix` and `index` steps need neither).
    """

    finisher: Callable[[bool], SessionFinisher]
    transcription: Callable[[], OfflineTranscription]
    diarize: bool  # a diarizer is configured
    minutes: bool  # minutes are generated
    action_items: bool  # action items follow the minutes
    repair: Callable[[], None] | None = None  # crash recovery only (phase 17)


def transcribe_weight(store: SessionRepository, session_id: str, duration: float) -> float:
    """`2 + 60 × remaining / duration`: remaining is the audio the raw transcript does not cover
    yet, averaged over the channels. Estimated from the transcript alone, since at Stop the
    WAVs may not be final yet (the abandoned pipeline finalizes them)."""
    if duration <= 0:
        return 2.0
    points = resume_points(store.load_raw_transcript(session_id), CHANNELS)
    left = sum(max(0.0, duration - point.start) for point in points.values()) / len(points)
    return 2.0 + 60.0 * min(left, duration) / duration


def session_job(
    session_id: str,
    parts: JobParts,
    usage: GpuUsage,
    *,
    weight: float,
    closed: threading.Event | None,
    on_finished: Callable[[], None],
) -> ProcessingJob:
    """The job of `session_id`; `before` waits for the abandoned live pipeline (`closed`), so the
    resume points are computed from the final raw transcript and WAVs."""

    def transcribe(token: CancelToken, progress: Progress) -> None:
        parts.transcription().run(session_id, token, progress)

    steps: list[Step] = []
    if parts.repair is not None:
        repair = parts.repair
        steps.append(Step(StepKind.REPAIR, REPAIR_WEIGHT, False, lambda token, p: repair()))
    steps.append(Step(StepKind.TRANSCRIBE, weight, usage.speech, transcribe))
    steps.append(Step(StepKind.MIX, MIX_WEIGHT, False, lambda t, p: parts.finisher(False).mix()))
    if parts.diarize:
        steps.append(
            Step(
                StepKind.DIARIZE,
                DIARIZE_WEIGHT,
                usage.speakers,
                lambda token, p: parts.finisher(True).identify_speakers(token),
            )
        )
    if parts.minutes:
        steps.append(
            Step(
                StepKind.MINUTES,
                MINUTES_WEIGHT,
                usage.llm,
                lambda token, p: parts.finisher(True).write_minutes(token),
            )
        )
        if parts.action_items:
            steps.append(
                Step(
                    StepKind.ACTION_ITEMS,
                    ACTION_ITEMS_WEIGHT,
                    usage.llm,
                    lambda token, p: parts.finisher(True).extract_action_items(token),
                )
            )
    steps.append(
        Step(StepKind.INDEX, INDEX_WEIGHT, False, lambda t, p: parts.finisher(False).index())
    )

    def before() -> None:
        if closed is not None:
            closed.wait()

    return ProcessingJob(
        session_id=session_id, steps=tuple(steps), on_finished=on_finished, before=before
    )
