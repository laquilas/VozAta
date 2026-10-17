"""`python -m vozata minutes <session_dir>`: (re)generate a session's minutes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_minutes import EmptyTranscriptError, write_session_minutes
from vozata.ports import LanguageModelError, Localizer, SessionNotFoundError
from vozata.storage.files.folder import open_session_folder


def run_minutes(
    session_dir: Path,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    labeler: SpeakerLabeler,
    build_generator: Callable[[Settings, Localizer, str | None], MinutesGenerator],
) -> int:
    """Write `minutes.md` from the best transcript, in the language and with the template stored
    in `session.json`. A session folder belongs to the file backend, so the command works on the
    file backend of its parent."""
    t = localizer.t
    folder = open_session_folder(session_dir, settings.sample_rate)

    def generator(template: str | None) -> MinutesGenerator:
        return build_generator(settings, localizer, template)

    try:
        write_session_minutes(folder.repository, folder.session_id, generator, labeler)
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder.path))
        return 1
    except EmptyTranscriptError:
        console.say(t("cli.empty_transcript", folder=folder.path))
        return 1
    except LanguageModelError as error:
        console.say(t("cli.minutes_failed", reason=error))
        return 1
    console.say(t("cli.minutes_written", path=folder.minutes_file))
    return 0
