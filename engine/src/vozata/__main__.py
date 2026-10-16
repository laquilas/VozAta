"""Command line: `python -m vozata record ...` and `python -m vozata minutes <session_dir>`."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from vozata import __version__, bootstrap
from vozata.audio.devices import (
    default_input,
    default_loopback,
    list_input_devices,
    list_loopback_devices,
)
from vozata.cli.console import ConsoleObserver
from vozata.cli.minutes import run_minutes
from vozata.cli.record import print_devices, run_record
from vozata.config import ConfigError, load_settings
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
    minutes = commands.add_parser("minutes", help=t("cli.help.minutes"))
    minutes.add_argument("session_dir", type=Path, help=t("cli.help.session_dir"))
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
        if args.command == "minutes":
            return run_minutes(
                args.session_dir,
                settings,
                console,
                localizer,
                labeler,
                bootstrap.build_minutes_generator,
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


if __name__ == "__main__":
    sys.exit(main())
