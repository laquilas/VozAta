"""`python -m vozata recover [<session_dir> | --all]`: finish sessions a crash cut short (17)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer
from vozata.storage.recovery import RecoveryError, SessionRecovery
from vozata.storage.session_store import SessionNotFoundError, SessionStore

RecoveryFactory = Callable[[SessionStore | None], SessionRecovery]  # None: OUTPUT_DIR


def run_recover(
    session_dir: Path | None,
    build_recovery: RecoveryFactory,
    console: ConsoleObserver,
    localizer: Localizer,
) -> int:
    """Repair and finish one interrupted session (`session_dir`) or all of `OUTPUT_DIR`.

    Exit code 0 when every session was recovered (or there was none), 1 otherwise.
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
        recovery = build_recovery(SessionStore(folder.parent))
        try:
            recovery.store.read_meta(folder.name)
        except SessionNotFoundError:
            console.say(t("cli.session_not_found", folder=folder))
            return 1
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
        console.say(t("cli.recovered", folder=recovery.store.paths(session_id).root))
    return 1 if failed else 0
