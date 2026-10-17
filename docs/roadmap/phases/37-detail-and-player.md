# Phase 37 — Session detail page and in-app audio player

## Goal

Open a meeting as its own page with an audio player built in: play, seek, change speed and
channel, click a transcript line to jump to it, and follow the current line while it plays.

## Depends on

36, 32

## Read first

- `ui/CLAUDE.md`
- [phase 32](32-audio-in-sqlite.md) (`GET /sessions/{id}/audio/{channel}` with Range)
- [phase 36](36-meetings-by-day.md) (navigation from the list)
- `Views/HistoryView.axaml` (current detail), `ViewModels/SessionDetailViewModel.cs`

## Scope

**UI**

| File | Content |
|------|---------|
| `Views/SessionPage.axaml` | header: back button, editable title, date, duration, tags; actions: regenerate minutes (template picker), export (md/docx/pdf), delete. Tabs: **Minutes**, **Transcript**, **Speakers**, **Action items**, **Ask** (Ask moves from the docked panel into a tab, scoped to the session). Player bar docked at the bottom |
| `ViewModels/SessionPageViewModel.cs` | replaces `SessionDetailViewModel` (keep its tested behavior: edit mode, speakers, action items, live session) |
| `Services/IAudioPlayer.cs` + `Services/LibVlcAudioPlayer.cs` | port: `OpenAsync(uri)`, `Play`, `Pause`, `Seek(seconds)`, `Rate`, `Position` / `Duration` observable; implementation with **LibVLCSharp** (plays the HTTP stream with Range, no temp files). Registered in `App.axaml.cs`; tests use `FakeAudioPlayer` |
| `Views/PlayerBar.axaml` | play/pause, −10 s / +10 s, position slider with time labels, speed (0.75×–2×), channel selector (mixed / mic / system), volume |
| Transcript sync | clicking a segment seeks to `segment.start`; while playing, the current segment is highlighted and auto-scrolled (pausable when the user scrolls) |
| Search / Ask citations | opening a hit or a citation (`[session@hh:mm:ss]`) opens the page and seeks to that time |
| Resources | strings in en / pt-BR / es |

## Design notes

- LibVLC adds ~40 MB to the installer (native libs, x64 only); update `packaging/` and the
  installer test. If that is too big, the fallback is NAudio + `MediaFoundationReader` over a
  cached WAV — decide in the phase and record why.
- "Open in external player" stays as a menu item (downloads/materializes the WAV).
- The live session page shows no player (audio is still being written).

## Acceptance criteria

- [ ] ViewModel tests (fake player): play/pause/seek/rate/channel switch keeps position, segment
      click seeks, highlight follows position, citation opens and seeks, live session hides the
      player, existing detail behaviors still pass.
- [ ] Manual: open a migrated and a new meeting, play each channel, seek by clicking lines,
      2× speed; installer build plays audio on a clean machine (CI install test).
- [ ] Resource parity test passes.

## Tests

`SessionPageViewModelTests.cs`, `PlayerBarViewModelTests.cs`, existing
`SessionDetailViewModelTests.cs` cases moved over.

## Out of scope

Waveform rendering, audio editing/trimming, video.

## Kickoff prompt

> Execute phase 37 of the roadmap (`docs/roadmap/phases/37-detail-and-player.md`), following
> `docs/roadmap/README.md`.
