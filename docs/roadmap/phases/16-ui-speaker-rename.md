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

- [x] Engine tests: unknown id → 422, round trip, labels in transcript/export use names.
- [x] UI tests: rows built from transcript speakers, save payload, regenerate prompt shown only when
      minutes exist.
- [x] Resource parity test passes.

## Tests

`engine/tests/api/test_speakers.py`, `SpeakersViewModelTests.cs`.

## Out of scope

Remembering names across sessions.

## Kickoff prompt

> Execute phase 16 of the roadmap (`docs/roadmap/phases/16-ui-speaker-rename.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/16-ui-speaker-rename`
- **Status:** ready for PR
- **Updated:** 2026-10-17 14:00
- **Next step:** none (phase done). Manual check run 2026-10-17 through the engine API on a session copy with a hand-written diarized fixture: GET/PUT speakers (trimmed names, 422 `unknown_speaker`, empty name restores `User 2`), transcript and search labels show the names, and minutes regenerated with Ollama use them. The desktop click-through is still pending.

### Steps

- [x] Engine: merge names into `speakers.json`, `GET`/`PUT /sessions/{id}/speakers`
      (422 `unknown_speaker`), names in search hits; contract docs
- [x] UI client: `GetSpeakersAsync` / `UpdateSpeakersAsync` + DTOs
- [x] UI: `SpeakersViewModel` (rows, save, regenerate prompt) + "Speakers" tab in session detail
- [x] Acceptance criteria, README status, PR

### Decisions and notes

- Added `GET /sessions/{id}/speakers` (not in the original contract): the UI needs each
  speaker's current name and default label to build the rename rows. Routes live in their own
  module `api/routes/speakers.py` to stay out of `sessions.py` (phases 21 / 24).
- `PUT` merges: ids left out keep their names. Accepted ids are those of the best transcript,
  including `mic` and an undiarized `system`.
- Search hits (22) now also use the session's names.
- UI: `SpeakersViewModel` + `Views/SpeakersPanel.axaml` are a third "Speakers" tab of the session
  detail (hidden while live); `SessionDetailViewModel` only exposes `Speakers` and loads it after
  the transcript, so phases 21 / 24 touch little shared code. Saving reloads the whole detail.
- Re-running diarization (`python -m vozata diarize`) rewrites `speakers.json` without names.

### Manual check (pending, no microphone or GPU needed)

Real diarization is pending credentials (HF token), so use a hand-written diarized fixture:

1. Copy any finished session folder under `OUTPUT_DIR` (with `session.json`,
   `transcript.jsonl` and `minutes.md`) to a new folder named e.g. `20261017_100000`; set `"id"`
   in its `session.json` to the new name.
2. In it, write `transcript.diarized.jsonl` with one JSON segment per line, e.g.
   `{"segment_id": "mic-000001", "channel": "mic", "speaker_id": "mic", "start": 1.0, "end": 2.0, "text": "Good morning.", "words": []}`,
   `{"segment_id": "system-000001", "channel": "system", "speaker_id": "system:1", "start": 3.0, "end": 4.0, "text": "Hi, I am Alice.", "words": []}`,
   `{"segment_id": "system-000002", "channel": "system", "speaker_id": "system:2", "start": 5.0, "end": 6.0, "text": "Bruno here.", "words": []}`
   (copy the exact field set from a line of `transcript.jsonl` if it differs), and
   `speakers.json` = `{"system:1": {"name": null}, "system:2": {"name": null}}`.
3. Start the app (`dotnet run --project ui/src/VozAta.Desktop`), open History, select the session,
   open the **Speakers** tab: rows `Me`, `User 1`, `User 2` with their lines as hints.
4. Type `Alice` / `Bruno`, Save: the Transcript tab shows the names; the orange
   "Regenerate minutes with the new names" prompt appears (the folder has `minutes.md`). Click it
   (Ollama running): the minutes regenerate with the names.
5. Clear `Bruno` and Save: `User 2` returns. `speakers.json` changed; `transcript*.jsonl` did not.
6. Export Markdown: the names are in the transcript section. Switch the app language: the tab
   texts follow.
