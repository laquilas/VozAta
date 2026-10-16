"""`python -m vozata minutes <session_dir>`: (re)generate a session's minutes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_minutes import EmptyTranscriptError, write_session_minutes
from vozata.ports import LanguageModelError, Localizer
from vozata.storage.session_store import SessionNotFoundError, SessionStore


def run_minutes(
    session_dir: Path,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    labeler: SpeakerLabeler,
    build_generator: Callable[[Settings, Localizer], MinutesGenerator],
) -> int:
    """Write `minutes.md` from the best transcript, in the language stored in `session.json`."""
    t = localizer.t
    folder = session_dir.resolve()
    store = SessionStore(folder.parent)
    generator = build_generator(settings, localizer)
    try:
        path = write_session_minutes(store, folder.name, generator, labeler)
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder))
        return 1
    except EmptyTranscriptError:
        console.say(t("cli.empty_transcript", folder=folder))
        return 1
    except LanguageModelError as error:
        console.say(t("cli.minutes_failed", reason=error))
        return 1
    console.say(t("cli.minutes_written", path=path))
    return 0
