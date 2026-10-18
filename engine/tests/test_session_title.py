from __future__ import annotations

import pytest

from vozata.session_title import (
    MAX_TITLE_LENGTH,
    TitleTooLongError,
    normalize_title,
    stored_title,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   \t\n ", None),
        ("  Weekly sync  ", "Weekly sync"),
        ("Weekly\n  sync\tnotes", "Weekly sync notes"),
        ("Reunião de equipe", "Reunião de equipe"),
    ],
)
def test_titles_are_trimmed_and_blank_means_untitled(raw: str | None, expected: str | None) -> None:
    assert normalize_title(raw) == expected


def test_the_longest_title_is_accepted_after_trimming() -> None:
    title = "x" * MAX_TITLE_LENGTH

    assert normalize_title(f"  {title}  ") == title


def test_a_longer_title_is_rejected() -> None:
    with pytest.raises(TitleTooLongError) as error:
        normalize_title("x" * (MAX_TITLE_LENGTH + 1))

    assert error.value.max_length == MAX_TITLE_LENGTH == 200


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({}, None),
        ({"title": None}, None),
        ({"title": "  "}, None),
        ({"title": 42}, None),
        ({"title": "Planning"}, "Planning"),
    ],
)
def test_stored_title_reads_only_a_usable_string(
    meta: dict[str, object], expected: str | None
) -> None:
    assert stored_title(meta) == expected
