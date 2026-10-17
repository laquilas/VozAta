"""`python -m vozata diarize <session_dir> [--minutes]`: identify a stored session's speakers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import ConfigError, Settings
from vozata.diarization.session_diarization import diarize_session
from vozata.ports import Diarizer, Localizer
from vozata.storage.session_store import SessionNotFoundError, SessionStore


def run_diarize(
    session_dir: Path,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build_diarizer: Callable[[Settings], Diarizer],
    then_minutes: Callable[[], int] | None = None,
) -> int:
    """Write `transcript.diarized.jsonl` + `speakers.json`, even when `DIARIZATION_ENABLED` is off.

    With `then_minutes`, the minutes are generated again from the diarized transcript.
    """
    t = localizer.t
    folder = session_dir.resolve()
    store = SessionStore(folder.parent)
    try:
        store.read_meta(folder.name)
        found = diarize_session(
            store,
            folder.name,
            lambda: build_diarizer(settings),
            settings.min_speakers,
            settings.max_speakers,
        )
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder))
        return 1
    except ConfigError as error:
        console.say(t("cli.diarize_failed", reason=error.render(localizer)))
        return 1
    except Exception as error:
        console.say(t("cli.diarize_failed", reason=error))
        return 1
    if found is None:
        console.say(t("cli.no_system_speech", folder=folder))
        return 1
    console.say(t("cli.diarized", count=found, path=store.paths(folder.name).diarized_jsonl))
    return then_minutes() if then_minutes is not None else 0
