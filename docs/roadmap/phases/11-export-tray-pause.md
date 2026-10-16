# Phase 11 — Export, tray and pause

## Goal

Export minutes + transcript as Markdown, DOCX or PDF; run from the system tray; pause and resume
recording from the window and the tray. **Completes milestone M2.**

## Depends on

08, 09

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [api-contract.md](../api-contract.md) — `GET /sessions/{id}/export`, pause/resume rows
- [architecture.md](../architecture.md) §6 (pause semantics), §8 (transcript precedence)

## Scope

**Engine**

| File | Content |
|------|---------|
| `ports.py` | `DocumentExporter` port: `export(minutes_md, segments, labeler, meta) -> bytes`, `media_type`, `extension` |
| `export/markdown.py` | minutes + transcript appendix |
| `export/docx.py` | `python-docx`: headings, bullet lists, transcript table (time, speaker, text) |
| `export/pdf.py` | `fpdf2` with a bundled Unicode TTF (DejaVu Sans in `export/fonts/`, license file included) |
| `bootstrap.py` | `EXPORTERS` registry keyed by format |
| `api/routes/export.py` | `GET /sessions/{id}/export?format=` with `Content-Disposition` filename `<session_id>-minutes.<ext>` |

**UI**

| Item | Content |
|------|---------|
| Export | button in session detail → format picker → `StorageProvider` save dialog |
| Pause/Resume | button next to Stop; paused state shown (amber indicator, timer frozen) |
| Tray | Avalonia `TrayIcon`: menu Start / Pause–Resume / Stop / Show / Quit; icon reflects idle / recording / paused; option "minimize to tray" in UI preferences |

## Acceptance criteria

- [ ] Engine tests: each exporter produces a valid file (DOCX opens with python-docx, PDF starts
      with `%PDF` and contains accented text from pt-BR/es), unknown format → 400.
- [ ] UI tests: export flow with fake storage provider, pause/resume state machine, tray command
      routing.
- [ ] Manual: export the three formats of a pt-BR session and open them; pause 30 s → WAVs keep
      alignment and no transcript lines appear during the pause.
- [ ] Resource parity test passes.

## Tests

`engine/tests/export/test_markdown.py`, `test_docx.py`, `test_pdf.py`, `tests/api/test_export.py`;
`ExportViewModelTests.cs`, `PauseResumeTests.cs`, `TrayViewModelTests.cs`.

## Out of scope

Speaker names in exports (16 extends the labeler), action items in exports (23).

## Kickoff prompt

> Execute phase 11 of the roadmap (`docs/roadmap/phases/11-export-tray-pause.md`), following
> `docs/roadmap/README.md`.
