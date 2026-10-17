# Phase 16 — UI speaker rename

## Goal

Let the user replace `User 1`, `User 2`, … with real names per session; names apply to the
transcript view, minutes regeneration and exports.

## Depends on

09, 14

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [api-contract.md](../api-contract.md) — `PUT /sessions/{id}/speakers`
- [architecture.md](../architecture.md) §8 (`speakers.json`), §11

## Scope

**Engine**: `PUT /sessions/{id}/speakers` (validates ids exist in the transcript, trims names, empty
name = back to default) → `speakers.json`; `SpeakerLabeler` reads names for transcript responses,
minutes and exporters.

**UI**: "Speakers" panel in session detail: one row per `system:<n>` with default label, first two
text snippets as a hint, name TextBox; Save → transcript refresh; when minutes already exist, offer
"Regenerate minutes with the new names".

## Design notes

- Raw files are never rewritten; only `speakers.json` changes.
- The microphone label (`Me`) can be renamed too (`mic` id) — useful for shared recordings.

## Acceptance criteria

- [ ] Engine tests: unknown id → 422, round trip, labels in transcript/export use names.
- [ ] UI tests: rows built from transcript speakers, save payload, regenerate prompt shown only when
      minutes exist.
- [ ] Resource parity test passes.

## Tests

`engine/tests/api/test_speakers.py`, `SpeakersViewModelTests.cs`.

## Out of scope

Remembering names across sessions.

## Kickoff prompt

> Execute phase 16 of the roadmap (`docs/roadmap/phases/16-ui-speaker-rename.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/16-ui-speaker-rename`
- **Status:** in progress
- **Updated:** 2026-10-17 12:00
- **Next step:** UI — `SpeakersViewModel` (+ `SpeakersViewModelTests.cs`), wire it into
  `SessionDetailViewModel.Speakers`, `Views/SpeakersPanel.axaml` as a "Speakers" tab, resx keys.

### Steps

- [x] Engine: merge names into `speakers.json`, `GET`/`PUT /sessions/{id}/speakers`
      (422 `unknown_speaker`), names in search hits; contract docs
- [x] UI client: `GetSpeakersAsync` / `UpdateSpeakersAsync` + DTOs
- [ ] UI: `SpeakersViewModel` (rows, save, regenerate prompt) + "Speakers" tab in session detail
- [ ] Acceptance criteria, README status, PR

### Decisions and notes

- Added `GET /sessions/{id}/speakers` (not in the original contract): the UI needs each
  speaker's current name and default label to build the rename rows. Routes live in their own
  module `api/routes/speakers.py` to stay out of `sessions.py` (phases 21 / 24).
- `PUT` merges: ids left out keep their names. Accepted ids are those of the best transcript,
  including `mic` and an undiarized `system`.
- Search hits (22) now also use the session's names.
