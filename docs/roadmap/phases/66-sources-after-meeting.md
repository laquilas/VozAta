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
| `storage/sqlite/migrations/NNN_sources.sql` | `source_chunks` (like `audio_chunks`, by `source_id`), `session_sources` |
| ingest, `ingest_check.py` | `live/<id>/sources/*` stored and checked before `live/<id>` is deleted |
| `processing/source_remix.py` | the selected sources re-mixed (phase 65 `automix`) into `audio_chunks` |
| `api/routes/sessions.py` | `GET /sessions/{id}/sources`, `POST /sessions/{id}/sources`, `GET /sessions/{id}/sources/{source_id}/audio` |
| job | re-run from `transcribe` after a new selection |
| prune | unselected sources after `SOURCES_KEEP_DAYS`; `POST /sessions/{id}/sources/prune` |

**UI**: the meeting page "Audio sources" panel (checkboxes, score, preview, "Apply and
regenerate", "Keep only the selected"); strings in en / pt-BR / es.

## Acceptance criteria

- [ ] A recorded meeting lists its sources with the final selection.
- [ ] Changing the selection rebuilds the tracks and regenerates transcript, speakers and minutes.
- [ ] Unselected sources are pruned after `SOURCES_KEEP_DAYS` or on request.
- [ ] en / pt-BR / es parity; coverage ≥ 80 %.

## Out of scope

Transcribing each source on its own track.

## Kickoff prompt

> Execute phase 66 of the roadmap (`docs/roadmap/phases/66-sources-after-meeting.md`),
> following `docs/roadmap/README.md`.
