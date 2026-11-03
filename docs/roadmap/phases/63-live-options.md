# Phase 63 — Options editable during the recording

## Goal

The conversation language, translate-to, minutes template, meeting terms, live transcription
and "generate minutes" can be changed while recording or paused. Each change applies live in
the engine and is stored in `session.json`. Devices stay fixed for the whole recording.

Requested by the user on 2026-11-03.

## Depends on

61

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`, [phase 35](35-toggl-shell.md) (title `PATCH`),
  [phase 41](41-record-only.md), [phase 29](29-live-translation.md)
- `api/routes/sessions.py`, `schemas.UpdateSession`, `SessionManager.rename`, `session.py`,
  `session_pipeline.py`, `session_live.py`, `transcription/language_lock.py`,
  `transcription/stitcher.py`, `transcription/offline.py`, `RecorderPageViewModel.cs`

## Scope

**Engine**

| File | Content |
|------|---------|
| `api/schemas.py`, `routes/sessions.py` | `PATCH /sessions/{id}`: `title`, `language`, `translate_to`, `template`, `vocabulary`, `live_transcription`, `generate_minutes`, each optional; a meeting that is not live takes only title, template and the minutes flag (`409 session_not_live`) |
| `api/session_manager.py` | `update(id, SessionChanges)` replaces `rename`; options mirrored to the recorder |
| `session.py` | `RecordingSession.apply(changes)` |
| `session_meta.py` | setters; `translate_to` stored; `live_transcription_spans` |
| `transcription/language_lock.py`, `stitcher.py` | `LanguageLock.set` (`auto` detects again); hints settable |
| `session_pipeline.py`, `session_live.py`, `output/sinks.py` | live transcription on / off at runtime; sinks added and removed (translation) |
| `transcription/offline.py`, `resume.py` | at Stop, only the audio not transcribed live (the uncovered spans) |
| Observer, `api` | `session_updated` event |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client` | `UpdateSessionAsync(id, SessionUpdate)`, `SessionUpdatedEvent` |
| `Services/Debouncer.cs` | the title debounce, generalized |
| `RecorderPageViewModel.cs`, `RecorderPage.axaml` | the chips enabled while recording or paused (devices only when idle); each change sent debounced (to the recorder until the engine attaches); a failed change reverts the chip |
| Resources | strings in en / pt-BR / es |

## Design notes

- Turning live transcription on mid-recording transcribes from then on; the earlier audio is
  transcribed after Stop, so the transcript has no hole and no duplicate.
- Translation needs live transcription (`409 live_transcription_off`).
- Template and minutes flag are read by the processing job; nothing else changes.

## Acceptance criteria

- [ ] A language change applies to the next transcribed chunk and to `session.json`.
- [ ] A term added mid-recording is a hint from the next chunk on.
- [ ] Translation turned on / off mid-recording starts / stops translating.
- [ ] Live transcription turned on mid-recording shows live lines; after Stop the earlier audio
      is transcribed; no duplicates.
- [ ] Template and minutes flag changes are used by the Stop job.
- [ ] en / pt-BR / es parity; coverage ≥ 80 %.

## Tests

`tests/test_session.py`, `tests/api/test_session_options.py`,
`tests/transcription/test_offline.py`, `RecorderPageViewModelTests.cs`, client tests.

## Out of scope

Changing devices during a recording.

## Kickoff prompt

> Execute phase 63 of the roadmap (`docs/roadmap/phases/63-live-options.md`), following
> `docs/roadmap/README.md`.
