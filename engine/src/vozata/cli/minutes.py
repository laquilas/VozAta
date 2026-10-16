"""`python -m vozata minutes <session_dir>`: (re)generate a session's minutes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.domain import ConversationLanguage
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
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
    try:
        meta = store.read_meta(folder.name)
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder))
        return 1
    segments = store.load_transcript(folder.name)
    if not segments:
        console.say(t("cli.empty_transcript", folder=folder))
        return 1
    language = ConversationLanguage(meta.get("language", ConversationLanguage.AUTO.value))
    generator = build_generator(settings, localizer)
    try:
        minutes = generator.generate(segments, labeler, language)
    except LanguageModelError as error:
        console.say(t("cli.minutes_failed", reason=error))
        return 1
    path = store.paths(folder.name).minutes_md
    path.write_text(minutes + "\n", encoding="utf-8", newline="\n")
    console.say(t("cli.minutes_written", path=path))
    return 0
