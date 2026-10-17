"""`transcript.translated.jsonl`: one `{segment_id, language, text}` line per translation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TextIO

from vozata.domain import Translation

_log = logging.getLogger(__name__)


class TranslationsFile:
    """Append translations; the file is created with the first one (none = no file)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: TextIO | None = None

    def append(self, translation: Translation) -> None:
        if self._file is None:
            self._file = self._path.open("a", encoding="utf-8", newline="\n")
        self._file.write(json.dumps(translation.to_dict(), ensure_ascii=False) + "\n")
        self._file.flush()  # on disk before the next one (crash safety)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def read_translations(path: Path) -> dict[str, Translation]:
    """Translations by segment id (the last line wins); empty when the file does not exist.

    Unreadable lines are skipped with a warning: the transcript is shown without them.
    """
    if not path.is_file():
        return {}
    translations: dict[str, Translation] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            translation = Translation.from_dict(json.loads(line))
        except (ValueError, KeyError, TypeError):
            _log.warning("Skipping an unreadable line of %s", path)
            continue
        translations[translation.segment_id] = translation
    return translations
