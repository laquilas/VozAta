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

- [x] Engine tests: each exporter produces a valid file (DOCX opens with python-docx, PDF starts
      with `%PDF` and contains accented text from pt-BR/es), unknown format → 400.
- [x] UI tests: export flow with fake storage provider, pause/resume state machine, tray command
      routing.
- [x] Manual: export the three formats of a pt-BR session and open them; pause 30 s → WAVs keep
      alignment and no transcript lines appear during the pause.
- [x] Resource parity test passes.

## Tests

`engine/tests/export/test_markdown.py`, `test_docx.py`, `test_pdf.py`, `tests/api/test_export.py`;
`ExportViewModelTests.cs`, `PauseResumeTests.cs`, `TrayViewModelTests.cs`.

## Out of scope

Speaker names in exports (16 extends the labeler), action items in exports (23).

## Kickoff prompt

> Execute phase 11 of the roadmap (`docs/roadmap/phases/11-export-tray-pause.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/11-export-tray-pause`
- **Status:** ready for PR
- **Updated:** 2026-10-16 23:00
- **Next step:** open and merge the PR (combined draft in `__pr__/feature-11-export-tray-pause/`)

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `DocumentExporter` port + Markdown exporter — `6a627f2`
- [x] DOCX exporter (`python-docx`) — `40f139a`
- [x] PDF exporter (`fpdf2`, bundled DejaVu Sans + license) — `4615620`
- [x] `EXPORTERS` registry + `GET /sessions/{id}/export?format=` — `c2a8675`
- [x] UI export: client download, `IFileSaver` (StorageProvider), format picker in session detail — `79f2a25`
- [x] UI pause / resume: button next to Stop, amber paused state, frozen timer — `a78bf3e`
- [x] UI tray: `TrayViewModel` (Start, Pause–Resume, Stop, Show, Quit, state icon), minimize to tray — `275edec`
- [x] Manual: export md / docx / pdf of a pt-BR session; pause 30 s; criteria — this commit

### Decisions and notes

- New engine dependencies: `python-docx`, `fpdf2`; `pypdf` (dev) extracts PDF text in tests,
  because fpdf2 stores glyph ids, not readable text. DejaVu Sans regular + bold (2.37) and its
  license are bundled in `export/fonts/` for Unicode PDF text.
- The minutes Markdown is parsed once into blocks (headings, items, paragraphs) shared by the DOCX
  and PDF exporters; the Markdown exporter keeps the minutes text as written.
- Transcript source: the raw transcript for now (edited / diarized variants come with 14 and 21).
- **Manual check — export (2026-10-16).** Through `serve` (`APP_LANGUAGE=pt-BR`) on a copy of the
  9-minute Portuguese session: `md`, `docx` and `pdf` downloaded as `20261016_095109-minutes.<ext>`;
  the Markdown had 65 lines, the DOCX opened with python-docx (title "Reunião de 2026-10-16 09:51",
  a 33-row transcript table) and the 2-page PDF's extracted text contained "Duração", "Ata",
  "Transcrição" and "Português". (No PDF renderer on this machine, so the layout was not looked at.)
- **Manual check — pause.** `serve` + the TTS meeting on the speakers, pause 12 s into playback,
  resume 30 s later: `session.json` recorded the pause (39.4–69.4 s); `mic.wav`, `system.wav` and
  `mixed.wav` were all 99.337 s; `system.wav` peaked at 0 inside the pause vs 14844 just before;
  no transcript line started inside the pause — the sentence in progress was cut at 39.3 s and the
  three sentences spoken during the pause are absent, as intended.
- **Manual check — tray.** The desktop app's tray icon appeared in the notification area (Windows
  11 puts new icons in the hidden-icons overflow) as "VozAta — Ready".
