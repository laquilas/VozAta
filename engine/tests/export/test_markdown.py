from __future__ import annotations

from vozata.export.document import ExportDocument, Row, parse_blocks
from vozata.export.markdown import MarkdownExporter
from vozata.ports import DocumentExporter


def document(minutes: str | None = "## Summary\nShort meeting.") -> ExportDocument:
    return ExportDocument(
        title="Reunião de 2026-10-16 09:00",
        details=["Duração: 01:02:05", "Idioma: Português"],
        minutes_title="Ata",
        minutes_markdown=minutes,
        minutes_blocks=parse_blocks(minutes or ""),
        no_minutes="Nenhuma ata foi gerada para esta sessão.",
        transcript_title="Transcrição",
        columns=("Hora", "Falante", "Texto"),
        rows=[Row("00:00:02", "Eu", "Bom dia, ação!"), Row("00:01:05", "Outros", "Oi.")],
    )


def test_satisfies_the_port() -> None:
    exporter = MarkdownExporter()

    assert isinstance(exporter, DocumentExporter)
    assert (exporter.extension, exporter.media_type) == ("md", "text/markdown; charset=utf-8")


def test_minutes_then_the_transcript_as_utf8_markdown() -> None:
    text = MarkdownExporter().export(document()).decode("utf-8")

    assert text == (
        "# Reunião de 2026-10-16 09:00\n"
        "\n"
        "Duração: 01:02:05  \n"
        "Idioma: Português\n"
        "\n"
        "## Ata\n"
        "\n"
        "## Summary\n"
        "Short meeting.\n"
        "\n"
        "## Transcrição\n"
        "\n"
        "[00:00:02] **Eu:** Bom dia, ação!  \n"
        "[00:01:05] **Outros:** Oi.\n"
    )


def test_missing_minutes_are_said_in_words() -> None:
    text = MarkdownExporter().export(document(minutes=None)).decode("utf-8")

    assert "## Ata\n\n_Nenhuma ata foi gerada para esta sessão._\n" in text
