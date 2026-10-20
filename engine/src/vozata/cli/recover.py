"""`python -m vozata recover [<session_dir> | --all]`: finish sessions a crash cut short (17)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer, SessionNotFoundError, SessionObserver
from vozata.processing.job import ProcessingJob, run_job_inline
from vozata.storage.recovery import SessionRecovery

# The folder holding the sessions (a session folder's parent); None: OUTPUT_DIR.
RecoveryFactory = Callable[[Path | None], SessionRecovery]
# (sessions folder, session id, observer) -> the meeting's processing job, repair first (40)
ResumeJobFactory = Callable[[Path | None, str, SessionObserver], ProcessingJob]


def run_recover(
    session_dir: Path | None,
    build_recovery: RecoveryFactory,
    console: ConsoleObserver,
    localizer: Localizer,
    resume_job: ResumeJobFactory,
) -> int:
    """Repair and finish one interrupted session (`session_dir`) or all of `OUTPUT_DIR`.

    Every meeting is finished by its processing job, inline (phase 40): repair (which makes it
    `finalizing`), transcribe what the live transcript missed, then the stop steps. Exit code 0
    when every session was recovered (or there was none), 1 otherwise. An explicit folder may also
    be `finalizing` with `capture_ended_at` (a CLI `record` crashed in its job); `--all` leaves
    such meetings to `serve` (another process may still be running them).
    """
    t = localizer.t
    if session_dir is None:
        recovery = build_recovery(None)
        ids = recovery.find_interrupted()
        if not ids:
            console.say(t("cli.recover_none"))
            return 0
        output_dir: Path | None = None
    else:
        folder = session_dir.resolve()
        output_dir = folder.parent
        recovery = build_recovery(output_dir)
        try:
            recovery.store.read_meta(folder.name)
        except SessionNotFoundError:
            console.say(t("cli.session_not_found", folder=folder))
            return 1
        resumable = recovery.is_resumable(folder.name)
        if not resumable and folder.name not in recovery.find_interrupted():
            console.say(t("cli.recover_not_interrupted", folder=folder))
            return 1
        ids = [folder.name]
    failed = sum(
        not _finish(output_dir, session_id, recovery, resume_job, console, localizer)
        for session_id in ids
    )
    return 1 if failed else 0


def _finish(
    output_dir: Path | None,
    session_id: str,
    recovery: SessionRecovery,
    resume_job: ResumeJobFactory,
    console: ConsoleObserver,
    localizer: Localizer,
) -> bool:
    """Run one meeting's job inline; False when its repair gave up (it stays `interrupted`)."""
    t = localizer.t
    console.say(t("cli.recovering", id=session_id))
    run_job_inline(resume_job(output_dir, session_id, console))
    meta = recovery.store.read_meta(session_id)
    if meta.get("status") == "interrupted":  # the repair step gave up
        console.say(t("cli.recover_failed", id=session_id, reason=meta.get("recovery_error", "")))
        return False
    console.say(t("cli.recovered", folder=recovery.store.folder(session_id) or session_id))
    return True
