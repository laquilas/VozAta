"""`python -m vozata diarize <session_dir> [--minutes]`: identify a stored session's speakers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import ConfigError, Settings
from vozata.diarization.session_diarization import diarize_session
from vozata.ports import Diarizer, Localizer, SessionNotFoundError
from vozata.storage.files.folder import open_session_folder


def run_diarize(
    session_dir: Path,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build_diarizer: Callable[[Settings], Diarizer],
    then_minutes: Callable[[], int] | None = None,
) -> int:
    """Write `transcript.diarized.jsonl` + `speakers.json`, even when `DIARIZATION_ENABLED` is off.

    With `then_minutes`, the minutes are generated again from the diarized transcript. A session
    folder belongs to the file backend, so the command works on the file backend of its parent.
    """
    t = localizer.t
    folder = open_session_folder(session_dir, settings.sample_rate)
    try:
        folder.repository.read_meta(folder.session_id)
        found = diarize_session(
            folder.repository,
            folder.audio,
            folder.session_id,
            lambda: build_diarizer(settings),
            settings.min_speakers,
            settings.max_speakers,
        )
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder.path))
        return 1
    except ConfigError as error:
        console.say(t("cli.diarize_failed", reason=error.render(localizer)))
        return 1
    except Exception as error:
        console.say(t("cli.diarize_failed", reason=error))
        return 1
    if found is None:
        console.say(t("cli.no_system_speech", folder=folder.path))
        return 1
    console.say(t("cli.diarized", count=found, path=folder.diarized_file))
    return then_minutes() if then_minutes is not None else 0
