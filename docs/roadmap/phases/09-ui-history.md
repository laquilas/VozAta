# Phase 09 — UI session history

## Goal

Browse past sessions, read their transcript and minutes, regenerate minutes, and open the audio
files and the session folder.

## Depends on

07

## Read first

- `ui/CLAUDE.md`
- [api-contract.md](../api-contract.md) — `GET /sessions`, `GET /sessions/{id}`,
  `GET /sessions/{id}/transcript`, `GET|POST /sessions/{id}/minutes`, `minutes_ready`

## Scope

| Item | Content |
|------|---------|
| `ViewModels/HistoryViewModel.cs` | paged list (date, duration, conversation language, minutes yes/no), refresh, selection |
| `ViewModels/SessionDetailViewModel.cs` | tabs Transcript / Minutes; `RegenerateMinutesCommand` (busy state until `minutes_ready` or `error`); `OpenFolderCommand`, `OpenAudioCommand(track)` |
| `Services/ShellService.cs` | `IShellService.Open(path)` via `Process.Start` with `UseShellExecute = true` (default player / Explorer) |
| `Views/` | navigation between Recording and History; Markdown rendering of minutes (Markdown.Avalonia or equivalent maintained package) |
| Resources | new keys in the three `.resx` files |

## Design notes

- Audio files are opened from `SessionDetail.folder` (`mic.wav`, `system.wav`, `mixed.wav`); the
  engine runs locally, so no download endpoint is needed.
- The session currently recording appears at the top with a live badge and no regenerate button.

## Acceptance criteria

- [ ] ViewModel tests: paging, detail loading, regenerate flow (success, error event), shell calls
      with correct paths, empty states (no sessions, no minutes).
- [ ] Manual: open an old session, read minutes, play `mixed.wav`, regenerate minutes.
- [ ] Resource parity test passes.

## Tests

`HistoryViewModelTests.cs`, `SessionDetailViewModelTests.cs`.

## Out of scope

Editing (21), search (22), speaker rename (16), action items (23), export (11).

## Kickoff prompt

> Execute phase 09 of the roadmap (`docs/roadmap/phases/09-ui-history.md`), following
> `docs/roadmap/README.md`.
