# Phase 21 — Editable transcript

## Goal

Let the user correct the transcript in the UI, with low-confidence words highlighted, before
(re)generating minutes. Raw data is preserved.

## Depends on

09

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §8 (transcript precedence, `transcript.edited.jsonl`)
- [api-contract.md](../api-contract.md) — `PUT /sessions/{id}/transcript`,
  `DELETE /sessions/{id}/transcript/edits`

## Scope

**Engine**: `PUT` validates segment ids against the current best transcript, rejects empty text,
writes the full edited copy to `transcript.edited.jsonl` (atomic); a segment whose text changed gets
`edited: true` and `words: []`; `DELETE` removes the edited file. If the search index exists (22),
reindex the session. Add `edited` to the segment schema in api-contract and architecture §8.
`LOW_CONFIDENCE_THRESHOLD` added to `config.py`/`.env.example` and exposed in `GET /settings`.

**UI**: in session detail, the transcript tab gets an Edit mode: each segment becomes a TextBox; in
read mode words with `probability < LOW_CONFIDENCE_THRESHOLD` are highlighted (inline runs);
Save / Revert to original; unsaved-changes guard on navigation; "Regenerate minutes" suggested
after saving.

## Acceptance criteria

- [ ] Engine tests: precedence returns edited file, invalid id → 422, empty text → 422, words
      cleared on edited segments, DELETE reverts, raw file unchanged (hash compare).
- [ ] UI tests: highlight computation, dirty tracking, save payload contains only real changes,
      navigation guard, revert.
- [ ] Manual: fix a misheard word, regenerate minutes → the minutes use the correction.
- [ ] Resource parity test passes.

## Tests

`engine/tests/api/test_transcript_edit.py`, `TranscriptEditorViewModelTests.cs`.

## Out of scope

Merging/splitting segments, audio-synced playback per segment (backlog).

## Kickoff prompt

> Execute phase 21 of the roadmap (`docs/roadmap/phases/21-editable-transcript.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/21-editable-transcript`
- **Status:** in progress
- **Updated:** 2026-10-17 18:00
- **Next step:** UI — wire `TranscriptEditorViewModel` into `SessionDetailViewModel` (`Editor`,
  highlighted `Lines`), the guard into `HistoryViewModel` selection and `MainViewModel.ConfirmCloseAsync`,
  and the Edit mode into `HistoryView.axaml`.

### Steps

- [x] Engine: `TranscriptSegment.edited`, edit applier, store write/delete (atomic) — `ec83130`
- [x] Engine: `PUT /sessions/{id}/transcript`, `DELETE /sessions/{id}/transcript/edits`, reindex — `eeac8c9`
- [x] Engine: `LOW_CONFIDENCE_THRESHOLD` in `config.py`, `settings_fields.py`, `.env.example` — `b559d17`
- [x] Docs: `edited` in api-contract and architecture §8 — `79cff5a`
- [x] UI: `UpdateTranscriptAsync` / `RevertTranscriptAsync` in the client and the fake — `e83f085`
- [x] UI: `TranscriptEditorViewModel` (highlight, dirty, save, revert, guard)
- [ ] UI: transcript tab Edit mode, low-confidence highlight, navigation guard, strings (en/pt-BR/es)
- [ ] Acceptance criteria, README `done`, PR

### Decisions and notes

- `PUT` takes `{segments: [{segment_id, text, ...}]}`: only `segment_id` and `text` are read (a full
  `Segment` is accepted), so the UI sends only the segments it changed. The engine applies them to
  the current best transcript and writes the full copy. Codes: `422 unknown_segment`,
  `422 empty_segment_text`, `409 transcript_still_recording` (also for `DELETE`).
- `edited` is written to JSONL only when true, so raw/diarized lines keep their schema.
- A failing search reindex is logged and never fails a saved edit.

- The manual check (fix a misheard word, regenerate minutes) needs no microphone; its recipe is
  written here once the UI lands.
