"""`python -m vozata recover [<session_dir> | --all]`: finish sessions a crash cut short (17)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer, SessionNotFoundError, SessionObserver
from vozata.processing.job import ProcessingJob, run_job_inline
from vozata.storage.recovery import RecoveryError, SessionRecovery

# The folder holding the sessions (a session folder's parent); None: OUTPUT_DIR.
RecoveryFactory = Callable[[Path | None], SessionRecovery]
# (sessions folder, session id, observer) -> the processing job of a `finalizing` meeting (40)
ResumeJobFactory = Callable[[Path | None, str, SessionObserver], ProcessingJob]


def run_recover(
    session_dir: Path | None,
    build_recovery: RecoveryFactory,
    console: ConsoleObserver,
    localizer: Localizer,
    resume_job: ResumeJobFactory | None = None,
) -> int:
    """Repair and finish one interrupted session (`session_dir`) or all of `OUTPUT_DIR`.

    Exit code 0 when every session was recovered (or there was none), 1 otherwise. An explicit
    folder that is `finalizing` with `capture_ended_at` (a CLI `record` crashed in its job) is
    finished with the processing job, inline; `--all` leaves such meetings to `serve` (another
    process may still be running them).
    """
    t = localizer.t
    if session_dir is None:
        recovery = build_recovery(None)
        ids = recovery.find_interrupted()
        if not ids:
            console.say(t("cli.recover_none"))
            return 0
    else:
        folder = session_dir.resolve()
        recovery = build_recovery(folder.parent)
        try:
            recovery.store.read_meta(folder.name)
        except SessionNotFoundError:
            console.say(t("cli.session_not_found", folder=folder))
            return 1
        if resume_job is not None and recovery.is_resumable(folder.name):
            return _resume(folder, recovery, resume_job, console, localizer)
        if folder.name not in recovery.find_interrupted():
            console.say(t("cli.recover_not_interrupted", folder=folder))
            return 1
        ids = [folder.name]
    failed = 0
    for session_id in ids:
        console.say(t("cli.recovering", id=session_id))
        try:
            recovery.recover(session_id, console)
        except RecoveryError as error:
            console.say(t("cli.recover_failed", id=session_id, reason=error))
            failed += 1
            continue
        console.say(t("cli.recovered", folder=recovery.store.folder(session_id) or session_id))
    return 1 if failed else 0


def _resume(
    folder: Path,
    recovery: SessionRecovery,
    resume_job: ResumeJobFactory,
    console: ConsoleObserver,
    localizer: Localizer,
) -> int:
    t = localizer.t
    session_id = folder.name
    console.say(t("cli.recovering", id=session_id))
    run_job_inline(resume_job(folder.parent, session_id, console))
    meta = recovery.store.read_meta(session_id)
    if meta.get("status") == "interrupted":  # the repair step gave up
        console.say(t("cli.recover_failed", id=session_id, reason=meta.get("recovery_error", "")))
        return 1
    console.say(t("cli.recovered", folder=recovery.store.folder(session_id) or session_id))
    return 0
