from __future__ import annotations

from pathlib import Path

from vozata.domain import Translation
from vozata.translation.translations_file import TranslationsFile, read_translations


def test_no_translation_creates_no_file(tmp_path: Path) -> None:
    path = tmp_path / "transcript.translated.jsonl"
    file = TranslationsFile(path)
    file.close()

    assert not path.exists()
    assert read_translations(path) == {}


def test_appends_lines_and_reads_them_by_segment_id(tmp_path: Path) -> None:
    path = tmp_path / "transcript.translated.jsonl"
    file = TranslationsFile(path)
    file.append(Translation("mic-000001", "pt", "Olá, é ótimo"))
    file.append(Translation("system-000002", "pt", "Tchau"))
    file.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"segment_id": "mic-000001", "language": "pt", "text": "Olá, é ótimo"}'
    assert read_translations(path) == {
        "mic-000001": Translation("mic-000001", "pt", "Olá, é ótimo"),
        "system-000002": Translation("system-000002", "pt", "Tchau"),
    }


def test_reading_skips_blank_and_unreadable_lines_and_the_last_line_wins(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(
        '{"segment_id": "a", "language": "pt", "text": "um"}\n'
        "\n"
        "not json\n"
        '{"segment_id": "b"}\n'
        '{"segment_id": "a", "language": "pt", "text": "dois"}\n',
        encoding="utf-8",
    )

    assert read_translations(path) == {"a": Translation("a", "pt", "dois")}
