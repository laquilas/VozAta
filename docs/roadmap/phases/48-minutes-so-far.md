# Phase 48 — Minutes so far and the partial-minutes list

## Goal

While a meeting is being recorded, the user clicks **Minutes so far** and gets minutes of what was
said up to that moment, **without stopping the recording** — "to show in the meeting what is
already settled". Each such result is kept on the meeting in a **Partial minutes** list; the final
minutes written after Stop stay separate and are never overwritten by them (user decision,
2026-10-22).

## Depends on

40, 41

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 40](40-background-processing.md) (queue, GPU gate, `session_still_active`),
  [phase 41](41-record-only.md) (live transcription off), [phase 24](24-ask-the-meeting.md)
- `minutes/generator.py`, `minutes/prompts.py`, `minutes/session_minutes.py`,
  `session_finisher.py`, `api/ask_job.py`, `api/minutes_job.py`, `api/routes/sessions.py`,
  `api/session_manager.py`, `processing/gpu_gate.py`, `ports.py` (`SessionRepository`),
  `storage/sqlite/*`, `storage/files/repository.py`, `locales/*.toml`
- UI: `RecorderPageViewModel.cs`, `RecorderPage.axaml`, `SessionPageViewModel.cs`,
  `SessionPage.axaml`, `MainViewModel.cs` (`Handle`), `VozAta.Client` (`EngineClient`, `Dtos`,
  `EngineEvents`)

## Current state (facts, 2026-10-22)

- `POST /sessions/{id}/minutes` refuses the recording session (409 `session_still_recording`) and
  runs through the processing queue; there is one minutes row per session (`minutes` table,
  `minutes.md`).
- Live segments are stored as they are committed (SQLite raw `segments`, `transcript.jsonl`), with
  times in seconds since the session start; `GET /sessions/{id}/transcript` reads them while
  recording.
- `MinutesGenerator.generate` takes any list of segments and does map-reduce over `LLM_MAX_CHARS`.
- `AskJob` runs outside the queue with the `ASK` GPU priority and works on an active session.

## Scope

**Data model**: `partial_minutes` — SQLite migration (`id, session_id, created_at, range_start,
range_end, origin (button|voice|range), template, markdown`); files backend
`partial_minutes/<id>.md` + `partial_minutes.json`. `SessionRepository` gains
`add_partial_minutes`, `list_partial_minutes`, `read_partial_minutes`, `delete_partial_minutes`;
deleting a meeting deletes them; the bundle export includes them.

**Engine**

| File | Content |
|------|---------|
| `minutes/segment_range.py` (new) | `segments_in_range(segments, start, end)`: a segment belongs when its start is in `[start, end)` |
| `minutes/generator.py`, `minutes/prompts.py` | `generate(..., scope=None)`; a scope line from `minutes.scope_live` ("The meeting is still in progress; this covers up to {end}.") or `minutes.scope_range` ("This covers only the part from {start} to {end}.") |
| `minutes/partial_minutes.py` (new) | `write_partial_minutes(store, session_id, generator, labeler, language, start, end, origin, template)`; `EmptyTranscriptError` for an empty range |
| `api/partial_minutes_job.py` (new) | like `AskJob`: one at a time, `GpuGate.priority(ASK)` when the LLM is on the local GPU; for the recording session it uses the live language lock and live labels, and `end` = now |
| `api/routes/partial_minutes.py` (new) | `POST /sessions/{id}/partial-minutes {start?, end?, template?}` → 202 `{partial_id}`; `GET` list; `GET /{pid}`; `DELETE /{pid}` |
| `locales/*.toml` | scope lines, error messages |

Errors: 409 `partial_minutes_in_progress`; 409 `live_transcription_off` for a recording without
live transcription; `error` events `empty_range`, `partial_minutes_failed`, `llm_unreachable`.
Event `partial_minutes_ready {partial_id, start, end, origin}`.

**UI**

- Recorder: a **Minutes so far** button in the timer bar, enabled while recording with live
  transcription on and no partial minutes being written; `OnSessionChanged` refreshes it. The
  result opens in a side panel (rendered markdown, Copy, Export `.md`) and a notification.
- Meeting page: a **Partial minutes** tab — list (created at, range, origin), view, copy, export,
  delete; reloaded on `partial_minutes_ready`. The Minutes tab is untouched.

**Docs**: `api-contract.md` (routes, event, error codes), `architecture.md` (data model, port),
user guide.

## Design notes

- Not the processing queue: the queue serves finished meetings in order, and a meeting still being
  recorded must get its answer now. Same model as Ask.
- With Ollama on this PC's GPU, the LLM shares the GPU with live Whisper (like Ask today); with a
  remote Ollama (phase 43) there is no contention.
- The live labels (`mic`, `system:<n>`) are the ones the recorder shows; final speaker names come
  after Stop and do not rewrite saved partial minutes.

## Acceptance criteria

- [ ] While recording, Minutes so far writes minutes of what was said until now; the recording
      goes on; the result shows in the recorder and is kept on the meeting.
- [ ] The meeting's Partial minutes tab lists, shows, copies, exports and deletes them; the final
      minutes after Stop are separate.
- [ ] Recording without live transcription: the button is disabled and the API answers 409.

## Tests

Engine: range filter edges; scope prompts in the three locales; job (busy, GPU priority, empty
range, LLM unreachable); routes (recording vs finished, unknown session); both storage backends;
delete and export. UI: button enablement and flow, side panel, Partial minutes tab, event
handling, resource parity.

## Out of scope

The range picker on a finished meeting (phase 49); voice commands (phase 50); editing partial
minutes; turning a partial into the final minutes.

## Kickoff prompt

> Start phase 48 (`docs/roadmap/phases/48-minutes-so-far.md`): read its *Read first* files, write
> `plans/48-minutes-so-far.md`, then implement it task by task.

## Progress

- **Branch:** `feature/48-minutes-so-far`
- **Status:** in progress
- **Updated:** 2026-10-22
- **Next step:** Task 1 of `plans/48-minutes-so-far.md` (storage of partial minutes, both backends).

### Steps

- [x] Implementation plan (`plans/48-minutes-so-far.md`)
- [ ] Storage of partial minutes (both backends, export / import)
- [ ] Range filter, scope line, `write_partial_minutes`
- [ ] Job, routes, events
- [ ] Desktop: recorder button and panel, Partial minutes tab
- [ ] Docs, full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- Live segments are stored as they are committed, so minutes so far read the stored transcript
  like a regeneration does (no access to the live pipeline); the conversation language is the one
  in the metadata (`auto` until it is detected).

