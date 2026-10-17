"""A recording session's live translation: worker → `transcript.translated.jsonl` + events."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from vozata.domain import Translation
from vozata.ports import SessionObserver, Translator
from vozata.translation.translations_file import TranslationsFile
from vozata.translation.worker import TranslationWorker


class _SessionOutput:
    """Write each translation to the session file, then send it as a `translation` event."""

    def __init__(self, path: Path, observer: SessionObserver) -> None:
        self._file = TranslationsFile(path)
        self._observer = observer

    def emit(self, translation: Translation) -> None:
        self._file.append(translation)
        self._observer.on_translation(
            translation.segment_id, translation.language, translation.text
        )

    def close(self) -> None:
        self._file.close()


def live_translation(
    target: str,
    load: Callable[[], Translator],
    path: Path,
    source: Callable[[], str | None],
    observer: SessionObserver,
    on_failed: Callable[[Exception], None],
) -> TranslationWorker:
    """A translation worker for one session; the caller starts it and the pipeline closes it."""
    return TranslationWorker(load, target, source, _SessionOutput(path, observer), on_failed)
