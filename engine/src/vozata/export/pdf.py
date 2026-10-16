"""PDF export with fpdf2 and the bundled DejaVu Sans (Unicode; see fonts/LICENSE-DejaVu.txt)."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from vozata.domain import ExportDocument

FONTS = Path(__file__).parent / "fonts"
FAMILY = "DejaVu"
_HEADING_SIZE = {"h1": 14, "h2": 12.5, "h3": 11.5}
_BODY = 10.5
_LINE = 5.5
_INDENT = 6
_COLUMN_WIDTHS = (18, 28, 110)  # mm: time, speaker, text
_GREY = (110, 110, 110)


class PdfExporter:
    media_type = "application/pdf"
    extension = "pdf"

    def export(self, document: ExportDocument) -> bytes:
        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_font(FAMILY, "", str(FONTS / "DejaVuSans.ttf"))
        pdf.add_font(FAMILY, "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        pdf.set_title(document.title)
        pdf.set_creator("VozAta")
        pdf.add_page()

        _text(pdf, document.title, size=18, bold=True)
        for line in document.details:
            _text(pdf, line, size=_BODY, color=_GREY)
        _section(pdf, document.minutes_title)
        if not document.minutes_blocks:
            _text(pdf, document.no_minutes, size=_BODY, color=_GREY)
        for block in document.minutes_blocks:
            if block.kind in _HEADING_SIZE:
                pdf.ln(1.5)
                _text(pdf, block.text, size=_HEADING_SIZE[block.kind], bold=True)
            elif block.kind == "bullet":
                _text(pdf, f"• {block.text}", size=_BODY, indent=_INDENT)
            elif block.kind == "numbered":
                _text(pdf, block.text, size=_BODY, indent=_INDENT)
            else:
                _text(pdf, block.text, size=_BODY)
        _section(pdf, document.transcript_title)
        if document.rows:
            pdf.set_font(FAMILY, "", 9.5)
            with pdf.table(
                col_widths=_COLUMN_WIDTHS,
                text_align="LEFT",
                headings_style=FontFace(emphasis="BOLD"),
                line_height=5,
            ) as table:
                header = table.row()
                for title in document.columns:
                    header.cell(title)
                for row in document.rows:
                    cells = table.row()
                    cells.cell(row.time)
                    cells.cell(row.speaker)
                    cells.cell(row.text)
        return bytes(pdf.output())


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(4)
    _text(pdf, title, size=15, bold=True)
    pdf.ln(1)


def _text(
    pdf: FPDF,
    text: str,
    *,
    size: float,
    bold: bool = False,
    indent: float = 0,
    color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    pdf.set_font(FAMILY, "B" if bold else "", size)
    pdf.set_text_color(*color)
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(pdf.epw - indent, _LINE * size / _BODY, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
