"""The processing job of one stopped meeting (phase 40): what Stop no longer does inline.

Steps, in order: `repair` (after a crash only), `transcribe` (the rest of the meeting from its
stored audio), `mix`, `diarize`, `minutes`, `action_items`, `index`; `on_finished` stamps the
meeting `done`. The WAVs are finalized by the abandoned live pipeline (or repaired) before the
job starts, so `mix` is the whole "finalize" part. Every step builds what it uses when it runs:
a cancelled step is redone by the queue with a fresh language model / diarizer, because a
cancelled one is closed for good.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
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

log = logging.getLogger(__name__)

CLOSED_WARNING_SECONDS = 300.0  # a cold model download can keep the live pipeline open 20+ min

MIX_WEIGHT = 1.0
DIARIZE_WEIGHT = 25.0
MINUTES_WEIGHT = 30.0
ACTION_ITEMS_WEIGHT = 10.0
INDEX_WEIGHT = 1.0
REPAIR_WEIGHT = 1.0


@dataclass(frozen=True)
class JobParts:
    """How a meeting is finished; `finisher` and `transcription` are called once per attempt.

    `finisher(kind)` gives the finisher of one step attempt, as a context manager: it builds only
    the model that step uses (the diarizer, the minutes generator or the action-item extractor;
    none for `mix` and `index`) and closes what it built when the attempt ends.
    """

    finisher: Callable[[StepKind], AbstractContextManager[SessionFinisher]]
    transcription: Callable[[], OfflineTranscription]
    diarize: bool  # a diarizer is configured
    minutes: bool  # minutes are generated
    action_items: bool  # action items follow the minutes
    repair: Callable[[], None] | None = None  # crash recovery only (phase 17)


_WEIGHTS = {
    StepKind.MIX: MIX_WEIGHT,
    StepKind.DIARIZE: DIARIZE_WEIGHT,
    StepKind.MINUTES: MINUTES_WEIGHT,
    StepKind.ACTION_ITEMS: ACTION_ITEMS_WEIGHT,
    StepKind.INDEX: INDEX_WEIGHT,
}


def _gpu(kind: StepKind, usage: GpuUsage) -> bool:
    """Whether a finisher step runs on the local GPU (and is cancelled by a priority user)."""
    if kind is StepKind.DIARIZE:
        return usage.speakers
    return usage.llm if kind in (StepKind.MINUTES, StepKind.ACTION_ITEMS) else False


def transcribe_weight(store: SessionRepository, session_id: str, duration: float) -> float:
    """`2 + 60 × remaining / duration`: remaining is the audio the raw transcript does not cover
    yet, averaged over the channels. Estimated from the transcript alone, since at Stop the
    WAVs may not be final yet (the abandoned pipeline finalizes them). A transcript that cannot be
    read yet (a crash cut its last line) counts as empty: only the estimate is pessimistic."""
    if duration <= 0:
        return 2.0
    try:
        segments = store.load_raw_transcript(session_id)
    except ValueError:  # a half-written last line after a crash: the repair step sets it aside
        segments = []
    points = resume_points(segments, CHANNELS)
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
    warn_every: float = CLOSED_WARNING_SECONDS,
) -> ProcessingJob:
    """The job of `session_id`; `before` waits for the abandoned live pipeline (`closed`), so the
    resume points are computed from the final raw transcript and WAVs. It never gives up (the
    transcript must be final first) but logs a warning every `warn_every` seconds."""

    def transcribe(token: CancelToken, progress: Progress) -> None:
        parts.transcription().run(session_id, token, progress)

    def finishing(kind: StepKind, run: Callable[[SessionFinisher, CancelToken], None]) -> Step:
        def attempt(token: CancelToken, progress: Progress) -> None:
            with parts.finisher(kind) as finisher:
                run(finisher, token)

        return Step(kind, _WEIGHTS[kind], _gpu(kind, usage), attempt)

    steps: list[Step] = []
    if parts.repair is not None:
        repair = parts.repair
        steps.append(Step(StepKind.REPAIR, REPAIR_WEIGHT, False, lambda token, p: repair()))
    steps.append(Step(StepKind.TRANSCRIBE, weight, usage.speech, transcribe))
    steps.append(finishing(StepKind.MIX, lambda finisher, token: finisher.mix()))
    if parts.diarize:
        steps.append(finishing(StepKind.DIARIZE, SessionFinisher.identify_speakers))
    if parts.minutes:
        steps.append(finishing(StepKind.MINUTES, SessionFinisher.write_minutes))
        if parts.action_items:
            steps.append(finishing(StepKind.ACTION_ITEMS, SessionFinisher.extract_action_items))
    steps.append(finishing(StepKind.INDEX, lambda finisher, token: finisher.index()))

    def before() -> None:
        if closed is None:
            return
        waited = 0.0
        while not closed.wait(warn_every):
            waited += warn_every
            log.warning(
                "still waiting for the live pipeline of meeting %s to close (%.0f s)",
                session_id,
                waited,
            )

    return ProcessingJob(
        session_id=session_id, steps=tuple(steps), on_finished=on_finished, before=before
    )
