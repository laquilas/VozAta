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

- [x] Engine tests: precedence returns edited file, invalid id → 422, empty text → 422, words
      cleared on edited segments, DELETE reverts, raw file unchanged (hash compare).
- [x] UI tests: highlight computation, dirty tracking, save payload contains only real changes,
      navigation guard, revert.
- [ ] Manual: fix a misheard word, regenerate minutes → the minutes use the correction.
      *(pending manual: recipe in Progress; needs Ollama, no microphone)*
- [x] Resource parity test passes.

## Tests

`engine/tests/api/test_transcript_edit.py`, `TranscriptEditorViewModelTests.cs`.

## Out of scope

Merging/splitting segments, audio-synced playback per segment (backlog).

## Kickoff prompt

> Execute phase 21 of the roadmap (`docs/roadmap/phases/21-editable-transcript.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/21-editable-transcript`
- **Status:** ready for PR
- **Updated:** 2026-10-17 19:30
- **Next step:** run the manual check recipe below (no microphone), then merge the PR.

### Steps

- [x] Engine: `TranscriptSegment.edited`, edit applier, store write/delete (atomic) — `ec83130`
- [x] Engine: `PUT /sessions/{id}/transcript`, `DELETE /sessions/{id}/transcript/edits`, reindex — `eeac8c9`
- [x] Engine: `LOW_CONFIDENCE_THRESHOLD` in `config.py`, `settings_fields.py`, `.env.example` — `b559d17`
- [x] Docs: `edited` in api-contract and architecture §8 — `79cff5a`
- [x] UI: `UpdateTranscriptAsync` / `RevertTranscriptAsync` in the client and the fake — `e83f085`
- [x] UI: `TranscriptEditorViewModel` (highlight, dirty, save, revert, guard) — `7e1fe4e`
- [x] UI: transcript tab Edit mode, low-confidence highlight, navigation guard, strings (en/pt-BR/es) — `667fb28`
- [x] Acceptance criteria, README `done`, PR

### Decisions and notes

- `PUT` takes `{segments: [{segment_id, text, ...}]}`: only `segment_id` and `text` are read (a full
  `Segment` is accepted), so the UI sends only the segments it changed. The engine applies them to
  the current best transcript and writes the full copy. Codes: `422 unknown_segment`,
  `422 empty_segment_text`, `409 transcript_still_recording` (also for `DELETE`).
- `edited` is written to JSONL only when true, so raw/diarized lines keep their schema.
- A failing search reindex is logged and never fails a saved edit.
- UI: `SessionDetailViewModel.Editor` (`TranscriptEditorViewModel`) owns Edit mode; read-mode lines
  get `LowConfidenceParts` from `LowConfidence.Split` (threshold read from `GET /settings`, default
  0.5; edited segments are never highlighted) and render through `Views/ConfidenceText`.
- Navigation guard: selecting another session in History (also via a search hit) and closing the
  window ask before dropping unsaved edits; a cleared list selection (refresh) keeps the editor.
  Switching the main tabs keeps the detail alive, so it needs no guard.

- Running `diarize` on a session that already has edits leaves `transcript.edited.jsonl` in place
  (it still wins); revert the edits first to see new speakers. Merging/splitting segments is out of
  scope.

### Manual check recipe (no microphone or speakers; needs Ollama with `OLLAMA_MODEL` pulled)

1. Pick a finished session with a transcript under `OUTPUT_DIR` (e.g. `engine/recordings/<id>/`)
   and note the raw file hash in PowerShell:
   `Get-FileHash engine/recordings/<id>/transcript.jsonl`.
2. Start Ollama, then the app from `ui/`: `dotnet run --project src/VozAta.Desktop` (it starts the
   engine; do not start a recording).
3. History → select the session → **Transcript** tab: words below `LOW_CONFIDENCE_THRESHOLD`
   (0.5) are highlighted and the hint line shows. To see more highlights, set the threshold to 0.9 in
   Settings → Transcription and reopen the session.
4. **Edit transcript** → fix one misheard word (a name or a term) → **Save corrections**. Expect:
   the banner "Transcript updated…" with **Regenerate minutes**, the line shows the fix without
   highlight, "This transcript includes your corrections." shows, the folder has
   `transcript.edited.jsonl` with `"edited": true, "words": []` on that line, and
   `Get-FileHash` of `transcript.jsonl` is unchanged.
5. Type the corrected word in the History search box → the hit opens the session at that line.
6. Click **Regenerate minutes** on the banner → when the minutes reload, the **Minutes** tab uses
   the corrected word.
7. Guard: **Edit transcript**, change a line, click another session → "Unsaved corrections"
   dialog; **Keep editing** stays on the session, **Discard** opens the other one. Change a line
   again and close the window → the same dialog.
8. **Revert to original** → confirm → `transcript.edited.jsonl` is gone and the original text
   (with highlights) is back.

API-only variant (engine from `engine/`: `../.venv/Scripts/python -m vozata serve`):

```powershell
$id = "<id>"; $api = "http://127.0.0.1:8765"
(Invoke-RestMethod "$api/sessions/$id/transcript").segments | Select-Object segment_id, text -First 5
Invoke-RestMethod -Method Put "$api/sessions/$id/transcript" -ContentType "application/json" `
  -Body '{"segments": [{"segment_id": "<segment id>", "text": "<corrected text>"}]}'
Invoke-RestMethod -Method Post "$api/sessions/$id/minutes" -ContentType "application/json" -Body '{}'
# wait for the minutes job (a few seconds to a minute), then:
(Invoke-RestMethod "$api/sessions/$id/minutes").markdown   # contains the correction
Invoke-RestMethod -Method Delete "$api/sessions/$id/transcript/edits"
```
