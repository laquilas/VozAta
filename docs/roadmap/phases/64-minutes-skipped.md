# Phase 64 — Minutes skipped at Stop, and the "minutes not generated" marker

## Goal

Back-to-back meetings never wait for minutes. A per-meeting "Generate minutes when finished"
option (editable during the recording); at Stop, when the engine core is not ready or the option
is off, the meeting is processed without minutes and marked **"Minutes not generated"**, with a
button to generate them later.

Requested by the user on 2026-11-03.

## Depends on

61

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`, [phase 40](40-background-processing.md),
  [phase 61](61-recorder-process.md) (`LiveRecordingImporter`)
- `bootstrap_processing.py`, `processing/session_job.py`, `api/minutes_job.py`,
  `api/payloads.py`, `MeetingRows.cs`, `MeetingsPage.axaml`, the meeting page's minutes tab

## Scope

**Engine**

| File | Content |
|------|---------|
| `api/schemas.py`, `session_manager.py`, `bootstrap.py`, `session_meta.py` | `generate_minutes` at start (null = `GENERATE_MINUTES`) and in `PATCH`, stored in `session.json` |
| `processing/readiness.py` | `MinutesReadiness`: is the language model reachable when the job is built |
| `bootstrap_processing.py`, `processing/session_job.py` | minutes (and action items) only when the setting, the meeting option and readiness allow it; otherwise `minutes_skipped: not_ready \| by_user` and a `minutes_skipped` event |
| `storage/live_import.py` | a recording imported because the engine was down is `not_ready` |
| `api/payloads.py`, `schemas.SessionSummary` | `minutes_state`: `generated`, `pending`, `skipped_not_ready`, `skipped_by_user`, `none` |
| `api/minutes_job.py` | generated minutes clear the marker |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client` | `MinutesState`, `GenerateMinutes`, `MinutesSkippedEvent` |
| `RecorderPageViewModel.cs`, `RecorderPage.axaml` | the "Generate minutes when finished" chip, remembered in `ui.json` |
| Meetings rows, meeting page | "Minutes not generated" badge (the reason in its tooltip) and a "Generate minutes" button |
| `MainViewModel.cs` | the event updates the row and shows a notification |
| Resources | strings in en / pt-BR / es |

## Acceptance criteria

- [x] Stop with the language model unreachable: the meeting ends `done` with transcript and
      speakers, marked `skipped_not_ready`; the badge and button show; the button produces the
      minutes and clears the badge.
- [x] The option off: `skipped_by_user`, same badge and button.
- [x] A recording imported after an engine outage is `skipped_not_ready`.
- [x] The next meeting can start at once after Stop. *(unchanged since phase 40; the recorder
      records the next one even while the engine processes)*
- [x] en / pt-BR / es parity; coverage ≥ 80 %.

## Tests

`tests/test_bootstrap_processing.py`, `tests/processing/test_session_job.py`,
`tests/api/test_minutes_state.py`, `MeetingsPageViewModelTests.cs`,
`RecorderPageViewModelTests.cs`.

## Out of scope

Generating the skipped minutes automatically when the language model comes back.

## Kickoff prompt

> Execute phase 64 of the roadmap (`docs/roadmap/phases/64-minutes-skipped.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/64-minutes-skipped` (stacked on `feature/63-live-options`, PR #81)
- **Status:** ready for PR
- **Updated:** 2026-11-03 19:23
- **Next step:** open the PR (base `feature/63-live-options`); then the manual checks in `__pendent__`.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Engine: `generate_minutes` start option and `PATCH` field, `minutes_not_ready` for a
      recording replayed after the engine was down, `minutes_skip_reason`, the job without minutes
      and the `minutes_skipped` marker + event, `minutes_state` in the summary, the marker cleared
      by generated minutes
- [x] UI: the chip, the row badge, the meeting page notice, the notification
- [x] Docs, full suites
- [ ] PR

### Decisions and notes

- "Engine not ready" is decided when the job is built: the recording stopped before the engine
  followed it (replayed later: `minutes_not_ready`), or the language model does not answer
  (`llm_reachable`). Then the meeting is processed (transcript, speakers, search) without minutes
  or action items, so the next meeting never waits.
- `GENERATE_MINUTES=false` turns minutes off for every meeting: no marker (`minutes_state: none`).
- No new readiness module: `processing/minutes_decision.py` holds the rule; the event goes through
  the job's observer (`on_minutes_skipped`, the API observer only).
- The "Generate minutes" button is the meeting page's existing **Regenerate minutes**; the
  page text points to it.
