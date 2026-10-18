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
- `Views/SessionDetailView.axaml` (current detail; phase 36 moved it out of the removed
  `HistoryView`, it sits on the right of `Views/MeetingsPage.axaml`), `ViewModels/SessionDetailViewModel.cs`

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

## Progress

- **Branch:** `feature/37-detail-and-player` (stacked on `feature/33-folder-migration`, PR #51,
  itself on `feature/32-audio-in-sqlite`, PR #49)
- **Status:** in progress
- **Updated:** 2026-10-18 20:19
- **Next step:** docs (architecture §16 / the UI section, api-contract unchanged), the phase file criteria and the manual check recipe (installer build plays audio: CI install test), then finish the phase.

### Steps

- [x] Start the phase (status, Progress)
- [x] `IAudioPlayer` port, `FakeAudioPlayer`; `TranscriptLine` gets `Start` / `End` / `IsCurrent`
- [x] `PlayerBarViewModel`: play/pause, ±10 s, seek, speed, channel (keeps position), volume
- [x] `SessionPageViewModel` replaces `SessionDetailViewModel` (tests moved), title edit,
      delete, Ask tab, segment click seeks, highlight follows position, live hides the player
- [x] Navigation: session page in the shell, back to Meetings; search hits / citations open it
      and seek
- [x] Views: `SessionPage.axaml`, `PlayerBar.axaml`, strings
- [x] `LibVlcAudioPlayer` (LibVLCSharp) wired in `App.axaml.cs`; packaging + install test check
- [ ] Docs, full suites, manual check recipe

### Decisions and notes

- Stacked on phase 33 (user's choice to stack on 32; 37's manual check needs a migrated meeting).
- `SessionDetailViewModel` was renamed to `SessionPageViewModel` (with its tests, `SessionPageViewModelTests.cs`) instead of rewritten: every tested behavior is kept and the page features are added to it.
- `IAudioPlayer` (`Services/AudioPlayer.cs`): `OpenAsync(uri)` (paused), `Play`, `Pause`, `Seek`, `Rate`, `Volume` (0–100), `Position`, `Duration`, `IsPlaying`, `PositionChanged` / `StateChanged` (any thread; the ViewModel posts through `IUiDispatcher`). `PlayerBarViewModel`: tracks in the order mixed, mic, system, only those in the detail's `audio`; the stream is opened on the first play; a slider move seeks (player-driven moves do not seek back); ±10 s clamped to the duration (remembered before the first play); switching track reopens and seeks back, playing only if it was; speeds 0.75–2×; volume and speed reapplied to each new stream; an open failure shows `Error`. `PositionMoved` drives the line highlight. New strings `Player*`, `Track*`.
- `SessionPageViewModel` page features: `Duration`; `Player` built after `GET /sessions/{id}` through the `Players` factory (none while live, without audio or without a factory); `PlayLine` plays from `TranscriptLine.Start`; `CurrentLine` / `TranscriptLine.IsCurrent` = the last line starting at or before the position (re-applied when the transcript reloads); `CueAt(seconds)` shows a moment without playing (kept until the player exists); title edit (`BeginRename` / `SaveRename` / `CancelRename`, blank = untitled, `Renamed` callback); `Delete` / `Back` call `DeleteMeeting` / `GoBack` (set by the owner); Ask tab = an `AskViewModel` scoped to the session whose citations focus the line and cue its time; `Dispose` releases the player. Tabs: 0 Minutes, 1 Transcript, 2 Speakers, 3 Action items, 4 Ask. **Tags** are not shown: sessions have no tags in the data model (no phase defines them).
- Navigation: `ShellViewModel.SessionPage` (+ `OpenSession` / `CloseSession`) is shown over the Meetings entry; picking any sidebar page while a meeting is open raises `SessionLeft`, and `MainViewModel` then closes it through `HistoryViewModel.CloseAsync` (which asks about unsaved edits; keeping them reopens the page). `HistoryViewModel` still owns the open meeting (`Detail`, now a `SessionPageViewModel`, disposed when replaced) and passes it `Players` / `Renamed` / `DeleteMeeting` (from `MainViewModel`: player bar over `players()` and `engineUri`, `Meetings.OnRenamedAsync`, `Meetings.DeleteMeetingAsync` = the row delete with its question and Undo) and `GoBack = CloseAsync`. `OpenSegmentAsync(id, segment, start)` cues `start` (search hits and citations carry it). Answer events also go to the open page's Ask. Views: `Views/SessionPage.axaml` (the class name clashes with the client DTO `VozAta.Client.SessionPage`; tests write `Views.SessionPage`), `Views/PlayerBar.axaml`, a play button per transcript line, `.current` style, "Follow playback" (`ScrollTarget` = the played line while following, else the search hit). The right-hand detail of `MeetingsPage.axaml` is gone. Render test frames: `session-minutes-*`, `session-transcript-playing-*`.
- **Player decision: LibVLCSharp 3.10.2 + VideoLAN.LibVLC.Windows 3.0.24, trimmed** (not NAudio, which has no pitch-keeping speed change). Only x64 and only the files an HTTP WAV stream needs ship: `libvlc.dll`, `libvlccore.dll`, `plugins/access/{libfilesystem,libhttp}_plugin.dll`, `plugins/demux/{libwav,libes}_plugin.dll`, `plugins/codec/libaraw_plugin.dll`, and the `audio_output`, `audio_filter` (scaletempo keeps the pitch at 2x), `audio_mixer`, `packetizer`, `stream_filter`, `misc`, `logger` folders: **11 MB instead of 109 MB** (the full package would have added ~40 MB compressed). A target marks them `ExcludeFromSingleFile`, so the single-file publish leaves `libvlc/win-x64/` next to the 101 MB exe (inside the bundle LibVLC would not find its plugins). `install-test.ps1` checks `libvlc.dll`, the mmdevice and http plugins, and no `win-x86`. `LibVlcAudioPlayer`: one `LibVLC` (`--no-video --quiet`) for the app, one `MediaPlayer` per page; `OpenAsync` parses the media (network, 10 s timeout) for the duration; a seek before playback starts is kept and applied on `Playing` from the thread pool (LibVLC must not be called from its event threads). Registered in `App.axaml.cs` as `Func<IAudioPlayer>` plus the engine base `Uri`. Smoke check: `LibVlcSmokeTests` (runs only with `VOZATA_LIBVLC_URL`) passed against a scratch engine on port 8799 serving a migrated 9-minute meeting: opened over HTTP, duration > 10 s, play from 2 s, 2x speed, seek to 8 s, pause holds the position (volume 0).





