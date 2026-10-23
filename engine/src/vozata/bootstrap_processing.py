"""Composition of a stopped meeting's processing job (phase 40), part of the composition root.

`bootstrap.py` calls `build_processing_job`; providers come from its registries, looked up when a
step runs (so a registry entry replaced at runtime, e.g. by tests, is honoured).
"""

from __future__ import annotations

import contextlib
import functools
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from vozata import bootstrap as root
from vozata.config import Settings
from vozata.domain import ConversationLanguage, SessionStatus, TranscriptSegment
from vozata.minutes.session_minutes import stored_vocabulary
from vozata.ports import (
    FallbackNotices,
    ModelDownloader,
    RecoverableStore,
    SessionAudio,
    SessionObserver,
    SessionRepository,
    StoreRepairError,
    Transcriber,
)
from vozata.processing.cancel import CancelToken
from vozata.processing.gpu_gate import GpuUsage
from vozata.processing.job import AbortJob, ProcessingJob, StepKind
from vozata.processing.session_job import JobParts, session_job, transcribe_weight
from vozata.session_finisher import SessionFinisher
from vozata.storage.recovery import SessionRecovery
from vozata.storage.session_folder import SessionFolder
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline import OfflineTranscription
from vozata.transcription.shared import SharedTranscriber
from vozata.vocabulary import build_hints
from vozata.worker_client.notices import ObserverNotices


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
    downloader: ModelDownloader | None = None,
) -> ProcessingJob:
    """The processing job of a stopped (or crashed, `repair`) meeting (phase 40).

    It starts once the abandoned live pipeline set `closed`. Each step builds its own providers
    when it runs, from `settings` and the meeting's `session.json`: a redone step never reuses a
    cancelled language model or diarizer. The rest of the transcript uses the conversation
    language stored in the metadata (selected, or detected live), so it is not detected again.
    With a `shared` Whisper (`WHISPER_KEEP_LOADED`) and speech on the GPU, the transcribe step
    leases it instead of loading a second model (the gate keeps live sessions off it meanwhile).
    Models not cached yet are fetched through `downloader` (default: the CLI's, phase 42).
    """
    downloader = root._downloader(settings, downloader)
    meta = store.read_meta(session_id)
    duration = float(meta.get("duration_seconds") or 0.0)
    after = settings.generate_minutes or settings.diarization_enabled  # VRAM rule

    @contextlib.contextmanager
    def finisher(kind: StepKind) -> Iterator[SessionFinisher]:
        """One step attempt's finisher: only that step's model is built, closed at the end."""
        built = root.build_finisher(
            settings, store, audio, observer, session_id, (kind,), downloader
        )
        try:
            yield built
        finally:
            built.close()

    def transcriber(token: CancelToken) -> Transcriber:
        if shared is not None and gate_usage.speech:
            # cancelled by a live start: keep the model, the live session leases it next
            return shared.lease(keep=not after, keep_when=lambda: token.cancelled)
        notices = ObserverNotices(observer, root.build_localizer(settings))
        return root.build_transcriber(settings, downloader, notices)

    def transcription(token: CancelToken) -> OfflineTranscription:
        return build_offline_transcription(
            settings, store, audio, session_id, functools.partial(transcriber, token)
        )

    def finished() -> None:
        with finisher(StepKind.INDEX) as done:  # no model
            done.ended(store.now())
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


def build_offline_transcription(
    settings: Settings,
    store: SessionRepository,
    audio: SessionAudio,
    session_id: str,
    transcriber: Callable[[], Transcriber] | None = None,
    on_segment: Callable[[TranscriptSegment], None] | None = None,
    downloader: ModelDownloader | None = None,
    notices: FallbackNotices | None = None,
) -> OfflineTranscription:
    """The transcription of what a meeting's raw transcript does not cover, built from its
    stored metadata: the conversation language (selected, or detected live; a language detected
    now is stored back), the session vocabulary and the configured chunker. The speech provider
    is `STT_PROVIDER` (its model fetched through `downloader`, default: the CLI's; a fallback
    from the worker told through `notices`) unless `transcriber` is given."""
    stored = store.read_meta(session_id)
    language = ConversationLanguage(stored.get("language", ConversationLanguage.AUTO.value))
    if transcriber is None:
        transcriber = functools.partial(
            root.build_transcriber, settings, root._downloader(settings, downloader), notices
        )
    return OfflineTranscription(
        settings,
        store,
        audio,
        transcriber,
        root.build_labeler(settings, root.build_localizer(settings)),
        LanguageLock(language, functools.partial(_detected, store, session_id)),
        build_hints(tuple(stored_vocabulary(stored))),
        functools.partial(root.CHUNKERS[settings.chunk_mode], settings),
        on_segment=on_segment,
    )


def build_transcribe_command(
    settings: Settings,
    folder: SessionFolder,
    on_segment: Callable[[TranscriptSegment], None] | None = None,
) -> OfflineTranscription:
    """The transcription the CLI `transcribe` runs on a stored meeting (phase 41)."""
    return build_offline_transcription(
        settings, folder.repository, folder.audio, folder.session_id, on_segment=on_segment
    )


def _detected(store: SessionRepository, session_id: str, language: ConversationLanguage) -> None:
    """Store the language `auto` mode detected while the rest of a meeting was transcribed."""
    meta = store.read_meta(session_id)
    store.write_meta(
        session_id, {**meta, "language": language.value, "language_source": "detected"}
    )


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
    recovery = SessionRecovery(store, repairs)
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
    observer.on_status(SessionStatus.FINALIZING, float(meta.get("duration_seconds") or 0.0))


def build_resume_job(
    settings: Settings,
    output_dir: Path | None,
    session_id: str,
    observer: SessionObserver,
) -> ProcessingJob:
    """The job the CLI `recover` runs inline on an `interrupted` meeting or one left `finalizing`
    (phase 40): repair (which makes it `finalizing`), transcribe the rest, then the stop steps.
    Nothing is gated or shared in the CLI."""
    return build_processing_job(
        settings,
        root.build_store(settings, output_dir),
        root.build_audio_store(settings, output_dir),
        observer,
        session_id,
        repair=True,
        closed=None,
        gate_usage=GpuUsage(speech=False, speakers=False, llm=False),
    )
