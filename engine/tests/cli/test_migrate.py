"""`python -m vozata migrate [--dry-run]` (phase 33)."""

from __future__ import annotations

import io
import sqlite3

from tests.api.test_migration import FakeImporter
from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.migrate import run_migrate
from vozata.labels import SpeakerLabeler


def _run(importer: FakeImporter | None, dry_run: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    return run_migrate(importer, dry_run, console, localizer), out.getvalue()


def test_migrate_imports_every_folder_with_a_progress_line() -> None:
    importer = FakeImporter(["a", "b"], bad={"b"})

    code, out = _run(importer)

    assert code == 0
    assert importer.imported == ["a"]
    assert out.splitlines() == [
        "cli.migrate_progress(done=1,folder=a,total=2)",
        "cli.migrate_progress(done=2,folder=b,total=2)",
        "cli.migrate_skipped(folder=/rec/b,message=migration.unreadable_json)",
        "cli.migrate_done(imported=1,skipped=1)",
    ]


def test_a_dry_run_lists_the_folders_and_imports_nothing() -> None:
    importer = FakeImporter(["a", "b"])

    code, out = _run(importer, dry_run=True)

    assert code == 0
    assert importer.imported == []
    assert out.splitlines() == ["cli.migrate_would(count=2)", "  a", "  b"]


def test_nothing_to_import() -> None:
    assert _run(FakeImporter([])) == (0, "cli.migrate_nothing\n")


def test_the_files_backend_has_nothing_to_import_into() -> None:
    assert _run(None) == (1, "cli.migrate_files_backend\n")


def test_a_short_disk_stops_with_the_sizes_in_mb() -> None:
    code, out = _run(FakeImporter(["a"], short="a"))

    assert code == 1
    assert out.splitlines()[-1] == "migration.no_space(folder=/rec/a,free=3,needed=6)"


def test_a_database_error_stops_with_the_reason() -> None:
    importer = FakeImporter(["a"])

    def locked(session_id: str) -> None:
        raise sqlite3.OperationalError("database is locked")

    importer.import_one = locked  # type: ignore[method-assign]

    code, out = _run(importer)

    assert code == 1
    assert out.splitlines()[-1] == "cli.migrate_failed(reason=database is locked)"
