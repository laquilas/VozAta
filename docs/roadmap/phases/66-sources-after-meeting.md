# Phase 66 — Sources kept per meeting; change the selection after the meeting

## Goal

After Stop, the meeting keeps every recorded source for a while. On the meeting page the user
sees the sources (score, selected, a preview player), changes which ones count, and VozAta
rebuilds the `mic` / `system` tracks from them and regenerates the transcript and the minutes.
Unselected sources are pruned after `SOURCES_KEEP_DAYS` (default 7), or at once with
"Keep only the selected".

## Depends on

65

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`, [phase 65](65-all-sources.md), [phase 32](32-audio-in-sqlite.md)
- `processing/session_job.py`, `processing/ingest_check.py`, `storage/sqlite/migrations/`,
  `storage/live_import.py`, `api/routes/sessions.py`, the meeting page

## Scope

**Engine**

| File | Content |
|------|---------|
| `storage/source_archive.py` | `OUTPUT_DIR/sources/<meeting>/`: the source files and `sources.json` (kind, name, selection, segments) |
| ingest, `ingest_check.py` | `live/<id>/sources/` moved to the archive before `live/<id>` is deleted |
| `processing/source_remix.py` | the selected sources re-mixed (phase 65 `automix`) into `audio_chunks` |
| `api/routes/sources.py`, `api/session_sources.py` | `GET` / `POST /sessions/{id}/sources`, `POST .../sources/keep-selected`, `GET .../sources/{source_id}/audio` |
| job | re-run from `transcribe` after a new selection |
| prune | unselected sources after `SOURCES_KEEP_DAYS`; `POST /sessions/{id}/sources/prune` |

**UI**: the meeting page's "Audio sources" tab (checkboxes, kind and length, "Apply and
regenerate" after a confirmation, "Keep only the ticked ones"); strings in en / pt-BR / es.

## Acceptance criteria

- [x] A recorded meeting lists its sources with the final selection.
- [x] Changing the selection rebuilds the tracks and regenerates transcript, speakers and minutes.
- [x] Unselected sources are pruned after `SOURCES_KEEP_DAYS` or on request.
- [x] en / pt-BR / es parity; coverage ≥ 80 %.

## Out of scope

Transcribing each source on its own track.

## Kickoff prompt

> Execute phase 66 of the roadmap (`docs/roadmap/phases/66-sources-after-meeting.md`),
> following `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/66-sources-after-meeting`
- **Status:** ready for PR
- **Updated:** 2026-11-12
- **Next step:** open the PR; then the manual check in `__pendent__` (a real recording with every device, then another choice on the meeting page).

### Steps

- [x] Start the phase (README status, Progress)
- [x] Engine: `SourceArchive`, `remix`, `TranscriptReset`, sources kept at ingest
- [x] Engine: `SessionSources`, routes, prune, delete with the meeting
- [x] UI: the meeting page's audio sources panel
- [x] Docs, full suites
- [ ] PR

### Decisions and notes

- The sources stay **files** (`OUTPUT_DIR/sources/<meeting>/`), not `source_chunks` rows: five
  devices add ~0.5 GB an hour, and the database is already 2 GB on the reference PC; files are
  pruned by deleting a folder.
- The tab has no player: `GET .../sources/{id}/audio` serves each source as WAV for a later one.
- A new choice rewrites both channels (`PcmImport.import_pcm`), drops every transcript
  (`TranscriptReset.reset_transcript`: edits are lost, the UI says so) and queues the meeting's
  usual job (`SessionManager.process_imported`), which transcribes, mixes, identifies speakers
  and writes the minutes again.
