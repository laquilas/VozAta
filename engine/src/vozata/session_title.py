"""Meeting titles (phase 35): optional, single-line, at most `MAX_TITLE_LENGTH` characters.

The title is a `session.json` field (`title`, null = untitled) written through the
`SessionRepository` port, so every storage backend keeps it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_TITLE_LENGTH = 200


class TitleTooLongError(ValueError):
    """The trimmed title is longer than `MAX_TITLE_LENGTH` (`422 title_too_long`)."""

    def __init__(self, max_length: int = MAX_TITLE_LENGTH) -> None:
        super().__init__(f"The title can have at most {max_length} characters")
        self.max_length = max_length


def normalize_title(raw: str | None) -> str | None:
    """Trim the title and collapse whitespace runs (new lines too) into one space.

    Blank or None means untitled (None); a longer title raises `TitleTooLongError`.
    """
    if raw is None:
        return None
    title = " ".join(raw.split())
    if not title:
        return None
    if len(title) > MAX_TITLE_LENGTH:
        raise TitleTooLongError
    return title


def stored_title(meta: Mapping[str, Any]) -> str | None:
    """The title saved in the metadata; None when absent, blank or not a string."""
    title = meta.get("title")
    return (title.strip() or None) if isinstance(title, str) else None
