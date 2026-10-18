from __future__ import annotations

from tests.fakes import FakeLocalizer
from vozata.domain import AppLanguage, Channel, TranscriptSegment
from vozata.export.document import Block, build_document, parse_blocks
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler

MINUTES = """# Minutes

## Summary
The team **agreed** to delay
the beta.

## Decisions
- Beta moves to *Tuesday*
* Carlos fixes the tests
1. Ana updates the notes
2) Decide on macOS
"""

SUMMARY = {
    "id": "20261016_090000",
    "started_at": "2026-10-16T09:00:05-03:00",
    "duration_seconds": 3725.6,
    "language": "pt",
}


def segment(start: float, speaker: str, text: str) -> TranscriptSegment:
    channel = Channel.MIC if speaker == "mic" else Channel.SYSTEM
    return TranscriptSegment(f"{speaker}-{start:g}", channel, speaker, start, start + 1, text, ())


def test_minutes_markdown_becomes_blocks() -> None:
    assert parse_blocks(MINUTES) == [
        Block("h1", "Minutes"),
        Block("h2", "Summary"),
        Block("p", "The team agreed to delay the beta."),
        Block("h2", "Decisions"),
        Block("bullet", "Beta moves to Tuesday"),
        Block("bullet", "Carlos fixes the tests"),
        Block("numbered", "1. Ana updates the notes"),
        Block("numbered", "2. Decide on macOS"),
    ]


def test_deep_headings_crlf_and_look_alikes() -> None:
    assert parse_blocks("#### Notes\r\n#hashtag\n-dash\n\n") == [
        Block("h3", "Notes"),
        Block("p", "#hashtag -dash"),
    ]
    assert parse_blocks("") == []


def test_the_document_has_localized_title_details_and_rows() -> None:
    localizer = TomlLocalizer(AppLanguage.PT_BR)
    segments = [segment(65.2, "system", " Oi, tudo bem? "), segment(2.4, "mic", "Bom dia.")]

    document = build_document(SUMMARY, MINUTES, segments, SpeakerLabeler(localizer), localizer)

    assert document.title == "Reunião de 2026-10-16 09:00"
    assert document.details == ["Duração: 01:02:05", "Idioma: Português"]
    assert (document.minutes_title, document.transcript_title) == ("Ata", "Transcrição")
    assert document.minutes_markdown == MINUTES.strip()
    assert document.minutes_blocks[0] == Block("h1", "Minutes")
    assert document.columns == ("Hora", "Falante", "Texto")
    assert [(row.time, row.speaker, row.text) for row in document.rows] == [
        ("00:00:02", "Eu", "Bom dia."),
        ("00:01:05", "Outros", "Oi, tudo bem?"),
    ]


def test_a_titled_meeting_uses_its_title_and_keeps_the_date_in_the_details() -> None:
    localizer = TomlLocalizer(AppLanguage.ES)
    summary = {**SUMMARY, "title": "Presupuesto 2027"}

    document = build_document(summary, MINUTES, [], SpeakerLabeler(localizer), localizer)

    assert document.title == "Presupuesto 2027"
    assert document.details == [
        "Fecha: 2026-10-16 09:00",
        "Duración: 01:02:05",
        "Idioma: Portugués",
    ]


def test_a_blank_title_falls_back_to_the_date_title() -> None:
    localizer = TomlLocalizer(AppLanguage.EN)

    document = build_document(
        {**SUMMARY, "title": "  "}, None, [], SpeakerLabeler(localizer), localizer
    )

    assert document.title == "Meeting of 2026-10-16 09:00"
    assert not any(detail.startswith("Date:") for detail in document.details)


def test_a_session_without_minutes_or_known_details_still_exports() -> None:
    localizer = FakeLocalizer()
    summary = {"id": "20261016_090000", "started_at": None, "duration_seconds": None}

    document = build_document(summary, None, [], SpeakerLabeler(localizer), localizer)

    assert document.title == "export.title(date=20261016_090000)"
    assert document.details == []
    assert document.minutes_markdown is None
    assert document.minutes_blocks == []
    assert document.no_minutes == "export.no_minutes"
    assert document.rows == []
