from __future__ import annotations

from pathlib import Path

from vozata.vocabulary import (
    MAX_HINT_CHARS,
    VocabularyStore,
    build_hints,
    merge_terms,
    normalize_terms,
)


def test_normalize_drops_blanks_comments_and_case_insensitive_duplicates() -> None:
    terms = ["  Avalonia ", "", "# a comment", "avalonia", "N5 Sensors", "AVALONIA", "  "]

    assert normalize_terms(terms) == ["Avalonia", "N5 Sensors"]


def test_normalize_splits_terms_with_line_breaks() -> None:
    assert normalize_terms(["Kubernetes\nGrafana\r\n\nkubernetes"]) == ["Kubernetes", "Grafana"]


def test_merge_puts_session_terms_first_and_keeps_their_spelling() -> None:
    merged = merge_terms(["vozata", "Jéssica"], ["Avalonia", "VozAta"])

    assert merged == ["vozata", "Jéssica", "Avalonia"]


def test_build_hints_joins_terms_with_commas() -> None:
    assert build_hints(["Avalonia", "N5 Sensors"]) == "Avalonia, N5 Sensors"


def test_build_hints_is_none_without_terms() -> None:
    assert build_hints([]) is None
    assert build_hints(["", "# only a comment"]) is None


def test_build_hints_keeps_whole_terms_in_order_up_to_the_limit() -> None:
    assert build_hints(["alpha", "beta", "gamma"], max_chars=11) == "alpha, beta"
    assert build_hints(["alpha", "beta", "gamma"], max_chars=10) == "alpha"


def test_build_hints_truncation_keeps_session_terms_first() -> None:
    session = ["Jéssica"]
    glossary = [f"term{i:03d}" for i in range(200)]

    hints = build_hints(merge_terms(session, glossary))

    assert hints is not None
    assert hints.startswith("Jéssica, term000")
    assert len(hints) <= MAX_HINT_CHARS
    assert "term199" not in hints


def test_build_hints_skips_everything_when_the_first_term_is_too_long() -> None:
    assert build_hints(["x" * 20], max_chars=10) is None


def test_store_reads_a_missing_file_as_empty(tmp_path: Path) -> None:
    assert VocabularyStore(tmp_path / "vocabulary.txt").read() == []


def test_store_parses_comments_blanks_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "vocabulary.txt"
    path.write_text(
        "﻿# Team glossary\nAvalonia\n\n  N5 Sensors  \n# people\navalonia\nJéssica\n",
        encoding="utf-8",
    )

    assert VocabularyStore(path).read() == ["Avalonia", "N5 Sensors", "Jéssica"]


def test_store_write_round_trips_and_returns_the_cleaned_terms(tmp_path: Path) -> None:
    store = VocabularyStore(tmp_path / "sub" / "vocabulary.txt")

    written = store.write(["Avalonia", " avalonia ", "", "N5 Sensors"])

    assert written == ["Avalonia", "N5 Sensors"]
    assert store.read() == written
    assert store.path.read_bytes() == b"Avalonia\nN5 Sensors\n"


def test_store_write_keeps_the_leading_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "vocabulary.txt"
    path.write_text("# Team glossary\n# one per line\nOld\n# later comment\nTerm\n", "utf-8")

    VocabularyStore(path).write(["New"])

    assert path.read_text("utf-8") == "# Team glossary\n# one per line\nNew\n"


def test_store_write_of_nothing_empties_the_file(tmp_path: Path) -> None:
    path = tmp_path / "vocabulary.txt"
    path.write_text("Old\n", "utf-8")

    assert VocabularyStore(path).write([]) == []
    assert path.read_text("utf-8") == ""


def test_store_write_keeps_a_header_only_file_as_header(tmp_path: Path) -> None:
    path = tmp_path / "vocabulary.txt"
    path.write_text("# Team glossary\n", "utf-8")

    VocabularyStore(path).write(["Avalonia"])

    assert path.read_text("utf-8") == "# Team glossary\nAvalonia\n"
