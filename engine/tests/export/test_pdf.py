from __future__ import annotations

import dataclasses
import io

import pypdf

from tests.export.test_markdown import document
from vozata.export.document import Row
from vozata.export.pdf import PdfExporter
from vozata.ports import DocumentExporter

MINUTES = """# Ata
## Decisões
A equipe decidiu adiar a versão beta para terça-feira.
- Lançamento na terça-feira
1. Ana atualiza as notas de versão
### Próximos passos
Revisão na segunda-feira."""


def text_of(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_satisfies_the_port() -> None:
    exporter = PdfExporter()

    assert isinstance(exporter, DocumentExporter)
    assert (exporter.extension, exporter.media_type) == ("pdf", "application/pdf")


def test_a_portuguese_session_keeps_its_accents() -> None:
    data = PdfExporter().export(document(MINUTES))

    assert data.startswith(b"%PDF")
    text = text_of(data)
    for expected in ("Reunião de 2026-10-16 09:00", "Duração: 01:02:05", "Decisões",
                     "terça-feira", "• Lançamento", "1. Ana atualiza as notas de versão",
                     "Próximos passos", "Transcrição", "Bom dia, ação!"):  # fmt: skip
        assert expected in text, expected


def test_a_spanish_session_keeps_its_accents_and_a_long_transcript_spans_pages() -> None:
    rows = [
        Row(f"00:{i // 60:02d}:{i % 60:02d}", "Otros", f"Acción número {i}: ¿mañana?")
        for i in range(120)
    ]
    spanish = dataclasses.replace(
        document("## Decisión\nSe aprobó el diseño."),
        title="Reunión del 2026-10-16 09:00",
        transcript_title="Transcripción",
        columns=("Hora", "Hablante", "Texto"),
        rows=rows,
    )

    data = PdfExporter().export(spanish)

    reader = pypdf.PdfReader(io.BytesIO(data))
    assert len(reader.pages) > 1
    text = text_of(data)
    for expected in ("Reunión del 2026-10-16 09:00", "Decisión", "Se aprobó el diseño.",
                     "Hablante", "Acción número 119: ¿mañana?"):  # fmt: skip
        assert expected in text, expected


def test_missing_minutes_and_an_empty_transcript() -> None:
    empty = dataclasses.replace(document(minutes=None), rows=[], details=[])

    text = text_of(PdfExporter().export(empty))

    assert "Nenhuma ata foi gerada para esta sessão." in text
    assert "Hora" not in text
