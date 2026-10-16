"""Markdown export: the minutes as written, then the transcript."""

from __future__ import annotations

from vozata.export.document import ExportDocument


class MarkdownExporter:
    media_type = "text/markdown; charset=utf-8"
    extension = "md"

    def export(self, document: ExportDocument) -> bytes:
        parts = [f"# {document.title}"]
        if document.details:
            parts.append("  \n".join(document.details))
        parts.append(f"## {document.minutes_title}")
        parts.append(document.minutes_markdown or f"_{document.no_minutes}_")
        parts.append(f"## {document.transcript_title}")
        if document.rows:
            parts.append(
                "  \n".join(f"[{row.time}] **{row.speaker}:** {row.text}" for row in document.rows)
            )
        return ("\n\n".join(parts) + "\n").encode("utf-8")
