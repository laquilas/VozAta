# Phase 62 — Engine gate, retry connection, reattach after a crash

## Goal

Only what needs the engine core is blocked while it is not connected, and the user sees why. A
**"Retry connection"** button starts or reconnects the engine and reloads its data. Recording
controls depend on the recorder only (phase 61). After an app crash, reopening VozAta shows the
running recording with its title, options and transcript so far. Closing the window while
recording offers to keep recording in the background.

Requested by the user on 2026-11-03.

## Depends on

61

## Read first

- `ui/CLAUDE.md`, [phase 61](61-recorder-process.md)
- `ViewModels/MainViewModel.cs` (`InitializeAsync`, `Handle`, `ConfirmCloseAsync`,
  `ShutdownAsync`), `Services/EngineProcess.cs`, `ViewModels/SettingsViewModel.cs`
  (`RestartEngineAsync`), `Views/ShellView.axaml` (banners, sidebar), `RecoveryViewModel.cs`,
  `App.axaml.cs` (`GuardClosing`)

## Scope

**Engine**

| File | Content |
|------|---------|
| `api/routes/sessions.py`, `schemas.py`, `session_manager.py` | `GET /sessions/current`: the live `SessionDetail` with its options; `404 no_active_session` |

**UI**

| File | Content |
|------|---------|
| `ViewModels/Models.cs` | `EngineStatus.Reconnecting` |
| `ViewModels/EngineGateViewModel.cs` | headline and detail per status, `RetryCommand` |
| `MainViewModel.cs` | `LoadEngineDataAsync` (extracted); `RetryConnectionAsync`; the event loop runs even after a failed start; one automatic respawn when the owned engine exits; data reloaded on reconnect |
| Views | the gate panel on Meetings, Ask, Config and the meeting page; never on the Recorder page |
| `SettingsViewModel.cs` | Restart engine refused and disabled while recording |
| `RecorderPageViewModel.cs` | `AdoptCurrentAsync`: state, elapsed, title and options from the recorder, then from `GET /sessions/current`; the transcript so far restored; a recording left by a dead recorder offers "Continue recording" / "Stop and process" |
| `MainViewModel.ConfirmCloseAsync`, `IDialogService` | while recording: Keep recording in background / Stop and close / Cancel; tray Quit uses it too |
| Resources | strings in en / pt-BR / es |

## Acceptance criteria

- [x] With an engine that fails to start, the app opens, Start records, and the engine pages
      show the gate with "Retry connection"; after fixing the cause Retry connects and loads
      settings, templates and meetings. *(tests; the real run is in `__pendent__`)*
- [x] Killing the engine during a recording shows "Connection lost"; recording goes on; the
      engine is started again once automatically. *(tests; real run in `__pendent__`)*
- [x] Killing the app during a recording and reopening it shows the recording, its options and
      the transcript so far. *(tests; real run in `__pendent__`)*
- [x] Closing while recording offers Keep / Stop / Cancel; Keep leaves recorder and engine
      running.
- [x] Restart engine is disabled while recording.
- [x] en / pt-BR / es parity; coverage ≥ 80 %.

## Tests

`EngineGateViewModelTests.cs`, `MainViewModelTests.cs`, `RecorderPageViewModelTests.cs`,
`SettingsViewModelTests.cs`, `tests/api/test_sessions.py`.

## Out of scope

Options edited during the recording (63); the minutes marker (64).

## Kickoff prompt

> Execute phase 62 of the roadmap (`docs/roadmap/phases/62-engine-gate.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/62-engine-gate` (stacked on `feature/61-recorder-process`, PR #79)
- **Status:** ready for PR
- **Updated:** 2026-11-03 18:29
- **Next step:** open the PR (base `feature/61-recorder-process`); then phase 63.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Engine: `GET /sessions/current`
- [x] UI: `EngineGateViewModel`, `RetryConnectionAsync`, data reloaded on reconnect, one automatic
      engine respawn, the event loop even after a failed start
- [x] UI: the gate panel on the engine pages; Restart engine disabled while recording
- [x] UI: reattach: transcript and options of a recording restored
- [x] UI: close while recording: keep recording in background / stop and close / cancel
- [x] Docs, full suites
- [ ] PR

### Decisions and notes

- Built in the phase 61 worktree (`E:\VozAta-work\wt61`), branch stacked on phase 61.
- The "dead recorder" card is not needed: the recorder continues a recording whose heartbeat is
  under 2 minutes old when it starts again (the app starts it), and closes older ones as
  `recorder_died` for the engine to import (phase 61). Nothing waits for the user.
- "Keep recording in the background" is offered only for a recorder recording: an engine-only
  recording (no recorder) keeps the old Stop-and-close question.
- The gate is one panel over the page area (MainViewModel.IsEngineGateVisible), not a
  separate view per page; the Recorder page is never covered.
