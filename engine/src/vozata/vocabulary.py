"""Custom vocabulary (phase 19): the global glossary file and speech-to-text hints.

The glossary is a UTF-8 text file with one term per line; blank lines and lines starting with `#`
are ignored and terms are deduplicated case-insensitively (the first spelling wins).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

MAX_HINT_CHARS = 500  # too many hints degrade accuracy
_COMMENT = "#"
_SEPARATOR = ", "


def normalize_terms(terms: Iterable[str]) -> list[str]:
    """Stripped, non-empty, non-comment terms, deduplicated case-insensitively, in order.

    A term holding line breaks becomes one term per line.
    """
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        for line in term.splitlines():
            cleaned = line.strip()
            key = cleaned.casefold()
            if not cleaned or cleaned.startswith(_COMMENT) or key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
    return result


def merge_terms(session_terms: Iterable[str], global_terms: Iterable[str]) -> list[str]:
    """Session terms first, then the glossary; duplicates keep the session spelling."""
    return normalize_terms([*session_terms, *global_terms])


def build_hints(terms: Iterable[str], max_chars: int = MAX_HINT_CHARS) -> str | None:
    """`terms` joined by commas, keeping whole terms in order up to `max_chars`; None if empty."""
    hints = ""
    for term in normalize_terms(terms):
        candidate = f"{hints}{_SEPARATOR}{term}" if hints else term
        if len(candidate) > max_chars:
            break
        hints = candidate
    return hints or None


class VocabularyStore:
    """Read and write the glossary file; a missing file is an empty glossary."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[str]:
        if not self.path.is_file():
            return []
        return normalize_terms(self.path.read_text(encoding="utf-8-sig").splitlines())

    def write(self, terms: Iterable[str]) -> list[str]:
        """Replace the terms (the comment lines at the top of the file are kept); returns them."""
        cleaned = normalize_terms(terms)
        lines = [*self._header(), *cleaned]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(lines) + "\n" if lines else ""
        self.path.write_text(text, encoding="utf-8", newline="\n")
        return cleaned

    def _header(self) -> list[str]:
        if not self.path.is_file():
            return []
        header: list[str] = []
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip().startswith(_COMMENT):
                break
            header.append(line.rstrip())
        return header
