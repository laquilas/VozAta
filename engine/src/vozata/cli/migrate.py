"""`python -m vozata migrate [--dry-run]`: import the old session folders into the database
(phase 33). `serve` does the same in the background at start."""

from __future__ import annotations

import sqlite3

from vozata.api.migration_job import Importer
from vozata.cli.console import ConsoleObserver
from vozata.ports import Localizer
from vozata.storage.migration import NotEnoughSpaceError

_MB = 1024 * 1024


def run_migrate(
    importer: Importer | None, dry_run: bool, console: ConsoleObserver, localizer: Localizer
) -> int:
    """0 when every pending folder was handled (some may be recorded as not imported); 1 when
    there is nothing to import into, the disk is short of space or the database fails."""
    t = localizer.t
    if importer is None:
        console.say(t("cli.migrate_files_backend"))
        return 1
    try:
        pending = importer.pending()
        if not pending:
            console.say(t("cli.migrate_nothing"))
            return 0
        if dry_run:
            console.say(t("cli.migrate_would", count=len(pending)))
            for session_id in pending:
                console.say(f"  {session_id}")
            return 0
        imported = skipped = 0
        for done, session_id in enumerate(pending):
            console.say(
                t("cli.migrate_progress", done=done + 1, total=len(pending), folder=session_id)
            )
            error = importer.import_one(session_id)
            if error is None:
                imported += 1
            else:
                skipped += 1
                message = t(f"migration.{error.reason}")
                console.say(t("cli.migrate_skipped", folder=error.folder, message=message))
    except NotEnoughSpaceError as error:
        needed, free = -(-error.needed // _MB), error.free // _MB
        console.say(t("migration.no_space", folder=error.folder, needed=needed, free=free))
        return 1
    except (sqlite3.Error, OSError) as error:
        console.say(t("cli.migrate_failed", reason=error))
        return 1
    console.say(t("cli.migrate_done", imported=imported, skipped=skipped))
    return 0
