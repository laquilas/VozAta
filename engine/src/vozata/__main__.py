"""Command line: `python -m vozata record | serve | minutes <dir> | diarize <dir> | reindex |
recover [<dir> | --all] | migrate [--dry-run] | transcribe <id>`."""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from fastapi import FastAPI

from vozata import __version__, bootstrap
from vozata.audio.devices import (
    default_input,
    default_loopback,
    list_input_devices,
    list_loopback_devices,
)
from vozata.bootstrap_processing import build_resume_job, build_transcribe_command
from vozata.cli.console import ConsoleObserver
from vozata.cli.diarize import run_diarize
from vozata.cli.migrate import run_migrate
from vozata.cli.minutes import run_minutes
from vozata.cli.record import print_devices, run_record
from vozata.cli.recover import run_recover
from vozata.cli.reindex import run_reindex
from vozata.cli.serve import run_serve
from vozata.cli.transcribe import run_transcribe
from vozata.config import ConfigError, Settings, load_settings
from vozata.domain import ConversationLanguage
from vozata.ports import Localizer


def tolerant_output(stream: TextIO) -> TextIO:
    """Replace characters the console cannot show instead of crashing on them."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    return stream


def build_parser(localizer: Localizer) -> argparse.ArgumentParser:
    t = localizer.t
    parser = argparse.ArgumentParser(prog="vozata", description=t("cli.help.description"))
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help=t("cli.help.record"))
    record.add_argument(
        "--language",
        choices=[language.value for language in ConversationLanguage],
        help=t("cli.help.language"),
    )
    record.add_argument("--mic", type=int, metavar="ID", help=t("cli.help.mic"))
    record.add_argument("--system", type=int, metavar="ID", help=t("cli.help.system"))
    record.add_argument("--list-devices", action="store_true", help=t("cli.help.list_devices"))
    commands.add_parser("serve", help=t("cli.help.serve"))
    minutes = commands.add_parser("minutes", help=t("cli.help.minutes"))
    minutes.add_argument("session_dir", type=Path, help=t("cli.help.session_dir"))
    diarize = commands.add_parser("diarize", help=t("cli.help.diarize"))
    diarize.add_argument("session_dir", type=Path, help=t("cli.help.session_dir"))
    diarize.add_argument("--minutes", action="store_true", help=t("cli.help.diarize_minutes"))
    commands.add_parser("reindex", help=t("cli.help.reindex"))
    recover = commands.add_parser("recover", help=t("cli.help.recover"))
    target = recover.add_mutually_exclusive_group(required=True)
    target.add_argument("session_dir", type=Path, nargs="?", help=t("cli.help.session_dir"))
    target.add_argument("--all", action="store_true", help=t("cli.help.recover_all"))
    migrate = commands.add_parser("migrate", help=t("cli.help.migrate"))
    migrate.add_argument("--dry-run", action="store_true", help=t("cli.help.migrate_dry_run"))
    transcribe = commands.add_parser("transcribe", help=t("cli.help.transcribe"))
    transcribe.add_argument("session", help=t("cli.help.transcribe_target"))
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stdin: TextIO | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    out = stdout or tolerant_output(sys.stdout)
    try:
        settings = load_settings(env)
    except ConfigError as error:
        out.write(f"{error}\n")
        return 2
    localizer = bootstrap.build_localizer(settings)
    args = build_parser(localizer).parse_args(argv)
    labeler = bootstrap.build_labeler(settings, localizer)
    console = ConsoleObserver(localizer, labeler, out)
    try:
        if args.command == "serve":
            return run_serve(settings, console, localizer, _build_app, _uvicorn_run)
        if args.command in ("minutes", "diarize"):
            open_folder = functools.partial(bootstrap.open_session_folder, settings)

            def minutes() -> int:
                return run_minutes(
                    args.session_dir,
                    settings,
                    console,
                    localizer,
                    labeler,
                    bootstrap.build_minutes_generator,
                    open_folder,
                )

            if args.command == "minutes":
                return minutes()
            return run_diarize(
                args.session_dir,
                settings,
                console,
                localizer,
                bootstrap.build_diarizer,
                minutes if args.minutes else None,
                open_folder,
            )
        if args.command == "reindex":
            return run_reindex(
                bootstrap.build_store(settings),
                bootstrap.build_search_index(settings),
                console,
                localizer,
            )
        if args.command == "migrate":
            return run_migrate(
                bootstrap.build_folder_importer(settings), args.dry_run, console, localizer
            )
        if args.command == "transcribe":
            return run_transcribe(
                args.session,
                settings,
                console,
                localizer,
                build_transcribe_command,
                functools.partial(bootstrap.open_session_folder, settings),
            )
        if args.command == "recover":
            return run_recover(
                None if args.all else args.session_dir,
                lambda output_dir: bootstrap.build_recovery(
                    settings, output_dir, stale_after=bootstrap.cli_stale_after(settings)
                ),
                console,
                localizer,
                lambda output_dir, session_id, observer: build_resume_job(
                    settings, output_dir, session_id, observer
                ),
            )
        if args.list_devices:
            return print_devices(
                console,
                localizer,
                list_input_devices(),
                list_loopback_devices(),
                (default_input(), default_loopback()),
            )
        return run_record(
            settings,
            console,
            localizer,
            bootstrap.build_session,
            language=ConversationLanguage(args.language) if args.language else None,
            mic_device=args.mic,
            system_device=args.system,
            stdin=stdin or sys.stdin,
        )
    except ConfigError as error:
        console.say(error.render(localizer))
        return 2
    except LookupError as error:  # an unknown --mic / --system id
        console.say(localizer.t("cli.device_not_found", reason=error))
        return 2
    except KeyboardInterrupt:
        return 130


def _build_app(settings: Settings) -> FastAPI:
    from vozata.api.app import create_app

    return create_app(bootstrap.build_api_container(settings))


def _uvicorn_run(app: FastAPI, **options: Any) -> None:  # pragma: no cover - starts a server
    import uvicorn

    uvicorn.run(app, **options)


if __name__ == "__main__":
    sys.exit(main())
