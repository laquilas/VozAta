"""Composition of a stopped meeting's processing job (phase 40), part of the composition root.

`bootstrap.py` calls `build_processing_job`; providers come from its registries, looked up when a
step runs (so a registry entry replaced at runtime, e.g. by tests, is honoured).
"""

from __future__ import annotations

import functools
import threading
from typing import NoReturn

from vozata import bootstrap as root
from vozata.config import Settings
from vozata.domain import ConversationLanguage, SessionStatus
from vozata.minutes.session_minutes import stored_vocabulary
from vozata.ports import (
    RecoverableStore,
    SessionAudio,
    SessionObserver,
    SessionRepository,
    StoreRepairError,
    Transcriber,
)
from vozata.processing.gpu_gate import GpuUsage
from vozata.processing.job import AbortJob, ProcessingJob
from vozata.processing.session_job import JobParts, session_job, transcribe_weight
from vozata.session_finisher import SessionFinisher
from vozata.storage.recovery import SessionRecovery
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline import OfflineTranscription
from vozata.transcription.shared import SharedTranscriber
from vozata.vocabulary import build_hints


def build_processing_job(
    settings: Settings,
    store: SessionRepository,
    audio: SessionAudio,
    observer: SessionObserver,
    session_id: str,
    *,
    repair: bool,
    closed: threading.Event | None,
    gate_usage: GpuUsage,
    shared: SharedTranscriber | None = None,
) -> ProcessingJob:
    """The processing job of a stopped (or crashed, `repair`) meeting (phase 40).

    It starts once the abandoned live pipeline set `closed`. Each step builds its own providers
    when it runs, from `settings` and the meeting's `session.json`: a redone step never reuses a
    cancelled language model or diarizer. The rest of the transcript uses the conversation
    language stored in the metadata (selected, or detected live), so it is not detected again.
    With a `shared` Whisper (`WHISPER_KEEP_LOADED`) and speech on the GPU, the transcribe step
    leases it instead of loading a second model (the gate keeps live sessions off it meanwhile).
    """
    meta = store.read_meta(session_id)
    duration = float(meta.get("duration_seconds") or 0.0)
    after = settings.generate_minutes or settings.diarization_enabled  # VRAM rule

    def finisher(models: bool) -> SessionFinisher:
        return root.build_finisher(settings, store, audio, observer, session_id, models)

    def transcriber() -> Transcriber:
        if shared is not None and gate_usage.speech:
            return shared.lease(keep=not after)
        return root._provider(root.TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)(settings)

    def transcription() -> OfflineTranscription:
        stored = store.read_meta(session_id)
        language = ConversationLanguage(stored.get("language", ConversationLanguage.AUTO.value))
        return OfflineTranscription(
            settings,
            store,
            audio,
            transcriber,
            root.build_labeler(settings, root.build_localizer(settings)),
            LanguageLock(language, functools.partial(_detected, store, session_id)),
            build_hints(tuple(stored_vocabulary(stored))),
            functools.partial(root.CHUNKERS[settings.chunk_mode], settings),
        )

    def finished() -> None:
        finisher(False).ended(store.now())
        length = float(store.read_meta(session_id).get("duration_seconds") or 0.0)
        observer.on_status(SessionStatus.DONE, length)

    parts = JobParts(
        finisher=finisher,
        transcription=transcription,
        diarize=settings.diarization_enabled,
        minutes=settings.generate_minutes,
        action_items=settings.generate_minutes and settings.extract_action_items,
        repair=functools.partial(_repair, settings, store, audio, observer, session_id)
        if repair
        else None,
    )
    weight = transcribe_weight(store, session_id, duration)
    return session_job(
        session_id, parts, gate_usage, weight=weight, closed=closed, on_finished=finished
    )


def _detected(store: SessionRepository, session_id: str, language: ConversationLanguage) -> None:
    """Store the language `auto` mode detected while the rest of a meeting was transcribed."""
    meta = store.read_meta(session_id)
    store.write_meta(
        session_id, {**meta, "language": language.value, "language_source": "detected"}
    )


def _no_stop_steps(session_id: str, observer: SessionObserver) -> NoReturn:
    raise RuntimeError("the processing job runs the stop steps itself")


def _repair(
    settings: Settings,
    store: SessionRepository,
    audio: SessionAudio,
    observer: SessionObserver,
    session_id: str,
) -> None:
    """Make a crashed meeting's audio and transcript readable (phase 17) and store its length.

    The meeting becomes `finalizing` with a `capture_ended_at` (a crash during capture had none),
    so another restart resumes it. When the data cannot be repaired it stays `interrupted` with
    `recovery_error`, an `error` event says so, and the job ends `failed` (`AbortJob`).
    """
    repairs = [part for part in (audio, store) if isinstance(part, RecoverableStore)]
    recovery = SessionRecovery(store, repairs, _no_stop_steps)
    try:
        length = recovery.repair(session_id)
    except StoreRepairError as error:
        recovery.fail(session_id, str(error))
        message = root.build_localizer(settings).t(
            "errors.api.recovery_failed", id=session_id, reason=error
        )
        observer.on_error("recovery_failed", message)
        raise AbortJob(str(error)) from error
    meta = store.read_meta(session_id)
    meta.pop("recovery_error", None)
    meta["status"] = SessionStatus.FINALIZING.value
    if not meta.get("capture_ended_at"):
        meta["capture_ended_at"] = store.now().isoformat(timespec="seconds")
    if length > 0:
        meta["duration_seconds"] = round(length, 3)
    store.write_meta(session_id, meta)
