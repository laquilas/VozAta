from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import wer_benchmark as bench  # noqa: E402


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("Vamos começar a reunião.", ["vamos", "começar", "a", "reunião"]),
        ("  Ótimo,   então — está decidido! ", ["ótimo", "então", "está", "decidido"]),
        ("Sexta-feira e terça-feira?", ["sexta-feira", "e", "terça-feira"]),
        ('O Carlos\'s "teste" (beta)', ["o", "carlos's", "teste", "beta"]),
        ("10:30, 2,5 e 3.000", ["10:30", "2,5", "e", "3.000"]),
        ("", []),
    ],
)
def test_normalize_keeps_accents_and_numbers_and_drops_punctuation(
    text: str, words: list[str]
) -> None:
    assert bench.normalize(text) == words


def test_identical_texts_have_no_errors() -> None:
    counts = bench.align(["a", "b", "c"], ["a", "b", "c"])

    assert counts == bench.Counts(substitutions=0, insertions=0, deletions=0, words=3)
    assert bench.wer(counts) == 0.0


def test_substitution_insertion_and_deletion_are_counted() -> None:
    reference = ["o", "carlos", "vai", "corrigir", "os", "testes", "hoje"]
    hypothesis = ["o", "carla", "vai", "corrigir", "todos", "os", "testes"]

    counts = bench.align(reference, hypothesis)

    # carlos -> carla (S), + todos (I), - hoje (D): the only alignment with 3 errors
    assert counts == bench.Counts(substitutions=1, insertions=1, deletions=1, words=7)
    assert bench.wer(counts) == pytest.approx(3 / 7)


def test_an_empty_hypothesis_deletes_every_word() -> None:
    counts = bench.align(["a", "b"], [])

    assert counts == bench.Counts(0, 0, 2, 2)
    assert bench.wer(counts) == 1.0


def test_an_empty_reference_counts_insertions_and_wer_stays_defined() -> None:
    counts = bench.align([], ["x"])

    assert counts == bench.Counts(0, 1, 0, 0)
    assert bench.wer(counts) == 1.0
    assert bench.wer(bench.Counts(0, 0, 0, 0)) == 0.0


def test_the_grid_is_the_cartesian_product_in_order() -> None:
    grid = bench.parse_grid(["CHUNK_MODE=vad,fixed", "CHUNK_SECONDS=4, 6"])

    assert grid == [
        {"CHUNK_MODE": "vad", "CHUNK_SECONDS": "4"},
        {"CHUNK_MODE": "vad", "CHUNK_SECONDS": "6"},
        {"CHUNK_MODE": "fixed", "CHUNK_SECONDS": "4"},
        {"CHUNK_MODE": "fixed", "CHUNK_SECONDS": "6"},
    ]
    assert bench.parse_grid([]) == [{}]


@pytest.mark.parametrize("item", ["CHUNK_SECONDS", "CHUNK_SECONDS=", "=4", "A=1,,2"])
def test_a_malformed_grid_item_is_refused(item: str) -> None:
    with pytest.raises(ValueError, match="KEY=value"):
        bench.parse_grid([item])


def test_the_report_is_a_markdown_table_sorted_by_wer() -> None:
    rows = [
        bench.Row("tts-meeting", {"CHUNK_SECONDS": "4"}, bench.Counts(3, 1, 2, 100), 30.0, 60.0),
        bench.Row("tts-meeting", {"CHUNK_SECONDS": "6"}, bench.Counts(1, 0, 1, 100), 15.0, 60.0),
    ]

    table = bench.render(rows).splitlines()

    assert table[0] == "| Benchmark | Configuration | WER | S | I | D | RTF |"
    assert table[2] == "| tts-meeting | CHUNK_SECONDS=6 | 2.0 % | 1 | 0 | 1 | 0.25 |"
    assert table[3] == "| tts-meeting | CHUNK_SECONDS=4 | 6.0 % | 3 | 1 | 2 | 0.50 |"


def test_the_default_configuration_is_named_as_such() -> None:
    row = bench.Row("b", {}, bench.Counts(0, 0, 0, 1), 1.0, 2.0)

    assert "| b | (settings defaults) | 0.0 % |" in bench.render([row])


def test_benchmarks_are_the_folders_with_a_reference_and_audio(tmp_path: Path) -> None:
    for name, files in (("full", ("reference.txt", "audio.wav")), ("no-audio", ("reference.txt",))):
        folder = tmp_path / name
        folder.mkdir()
        for file in files:
            (folder / file).write_text("x", encoding="utf-8")

    found = bench.find_benchmarks(tmp_path)

    assert [benchmark.name for benchmark in found] == ["full"]
    assert found[0].reference == ["x"]
    assert bench.find_benchmarks(tmp_path, only=["no-audio"]) == []


def test_the_committed_tts_reference_is_the_meeting_of_the_reference_machine() -> None:
    root = Path(__file__).resolve().parents[3] / "benchmarks" / "tts-meeting"

    words = bench.normalize((root / "reference.txt").read_text(encoding="utf-8"))

    assert words[:4] == ["vamos", "começar", "a", "reunião"]
    assert len(words) > 80
