# Phase 35 — Toggl-style shell and timer bar

## Goal

Replace the tab layout with a Toggl Track–style shell: a collapsible left sidebar, a page area,
and on the recorder page a timer bar at the top ("What is this meeting about?", chips, a big
timer and a round start/stop button). Meetings get a title.

## Depends on

34

## Read first

- `ui/CLAUDE.md`, `engine/CLAUDE.md`
- [phase 34](34-ui-design-system.md) (tokens, icons, control styles)
- [api-contract.md](../api-contract.md) — `POST /sessions`, `SessionSummary`
- `Views/MainWindow.axaml`, `ViewModels/MainViewModel.cs`

## Scope

**UI**

| File | Content |
|------|---------|
| `Views/ShellWindow.axaml` (replaces the `TabControl` in `MainWindow`) | left sidebar (`Brush.Sidebar`): logo, nav items with icon + label — **Recorder**, **Meetings**, **Ask**, **Config** — collapse to icons (state in `ui.json`); bottom: engine status dot (health), theme toggle. Right: `ContentControl` bound to `Shell.CurrentPage` with `DataTemplates` per page ViewModel. Notifications and the recovery card become toasts / a banner over the page area |
| `ViewModels/ShellViewModel.cs` | `Pages` list, `CurrentPage`, `NavigateCommand`; keyboard shortcuts (Ctrl+1…4); starts on Recorder |
| Split `MainViewModel` | `RecorderPageViewModel` (session state, timer, live transcript, devices, meters), `MeetingsPageViewModel` (wraps `HistoryViewModel` until phase 36), `AskPageViewModel` (wraps `AskViewModel`), `ConfigPageViewModel` (wraps `SettingsViewModel` until phase 38); shared session state in a `RecordingSessionService` so the sidebar can show a red "recording" dot and elapsed time on every page |
| `Views/RecorderPage.axaml` | **timer bar** (a card across the top): title `TextBox` with placeholder "What is this meeting about?", chips (template, conversation language, translate-to, mic/system device) that open small flyouts, `TextBlock.timer` `hh:mm:ss`, `Button.round-start` ▶ (accent) / `Button.round-stop` ■ (danger), pause button while recording. Below: level meters (slim bars inside the device chips) and the live transcript list. Title is editable while recording |
| Tray | unchanged behavior; tooltip shows the title when set |
| Resources | new strings (nav labels, placeholder, untitled) in en / pt-BR / es |

**Engine**

| File | Content |
|------|---------|
| API | `POST /sessions` accepts optional `title` (≤ 200 chars, trimmed); `PATCH /sessions/{id}` `{title}` (also while recording); `SessionSummary.title` (null = untitled) |
| Storage | `title` in `session.json` (file backend) / `sessions.title` (sqlite, phase 31 column); minutes prompt gets the title as context when set (all three locales); export uses it as the document title |
| Docs | api-contract, architecture §8 |

## Design notes

- Keep `MainWindow` as the window class name (tray, single-instance and tests rely on it); only
  its content changes.
- Start = Enter in the title box (like Toggl). Stop asks for nothing; the title can be edited
  later.
- The sidebar "Meetings" page is the current history until phase 36 redesigns it; "Config" is the
  current settings until phase 38.

## Acceptance criteria

- [x] ViewModel tests: navigation, shortcuts, recording indicator visible on every page, title
      sent on start and patched while recording, Enter starts, chips disabled while recording
      (except title).
- [x] Engine tests: `title` validation, PATCH while recording and after, title in summary,
      minutes prompt and export.
- [ ] Manual: record a meeting with a title from the new timer bar, navigate between pages while
      recording, stop; title shows in history, minutes and the exported docx. Screenshots light
      and dark in the PR. — *pending manual (audio hardware; recipe in Progress); headless
      screenshots light and dark attached to the PR*
- [x] Resource parity test passes.

## Tests

`ShellViewModelTests.cs`, `RecorderPageViewModelTests.cs`, `tests/api/test_session_title.py`,
`tests/minutes/test_prompt_title.py`.

## Out of scope

Meetings list redesign (36), detail page and player (37), Config redesign (38).

## Kickoff prompt

> Execute phase 35 of the roadmap (`docs/roadmap/phases/35-toggl-shell.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/35-toggl-shell`
- **Status:** ready for PR
- **Updated:** 2026-10-17 23:40
- **Next step:** run the manual check below on the reference machine (one phase at a time on the
  audio hardware), then merge the PR.

### Steps

- [x] Engine: `title` on start, in `session.json` and `SessionSummary`; contract suite — `9b1a671`
- [x] Engine: `PATCH /sessions/{id}` `{title}` while recording and after — `fc66b75`
- [x] Engine: title in the minutes prompt (en / pt-BR / es) and as the export document title —
      `2956745`, `dd74ba4`
- [x] Docs: api-contract, architecture §8 — `3ee4679`
- [x] UI client: `Title` on start and in `SessionSummary`, `UpdateSessionTitleAsync` — `6d283d5`
- [x] UI: `RecordingSessionService` + `RecorderPageViewModel` split out of `MainViewModel` —
      `068dd87`
- [x] UI: meeting title on the recorder page (sent on start, patched while recording, Enter
      starts), options locked while recording — `898f1e8`
- [x] UI: `ShellViewModel` (pages, navigation, Ctrl+1…4, sidebar collapse in `ui.json`) and the
      Meetings / Ask / Config page ViewModels — `9c7164f`
- [x] UI: shell view (sidebar, toasts, recovery banner) and the recorder page timer bar; tray
      tooltip with the title; strings in en / pt-BR / es — `fa907a9`
- [x] UI: headless renders of the new shell (idle and recording, light and dark) — `fa907a9`
- [x] Full suites (engine 1311 passed, 99.92 % coverage; UI 519 passed), `ruff`, `dotnet format`
      — fix `184d035`
- [ ] Manual check (pending, recipe below)

### Manual check recipe

Run on the reference machine, with no other phase using the audio devices.

1. `git checkout feature/35-toggl-shell`, then from `ui/`: `dotnet run --project src/VozAta.Desktop`
   (the app starts the engine on `http://127.0.0.1:8765`).
2. Shell: the app opens on **Recorder**; the sidebar lists Recorder, Meetings, Ask, Config.
   Ctrl+2, Ctrl+3, Ctrl+4, Ctrl+1 switch pages. Click the chevron: icons only; close and reopen the
   app: still collapsed (`%APPDATA%/VozAta/ui.json` has `"sidebar_collapsed": true`); expand
   again. The moon button flips light ↔ dark. The engine dot at the bottom is green.
3. Recorder: in the chips pick the microphone, the system output, the conversation language and
   the template. Type `Phase 35 check` in "What is this meeting about?" and press **Enter**: the
   recording starts (timer runs, red round stop button, chips greyed, meters move inside the two
   device chips while you speak and play some audio).
4. While recording, change the title to `Phase 35 manual check` and wait one second (or press
   Enter). Hover the tray icon: `VozAta — Recording: Phase 35 manual check`.
5. Press Ctrl+2, Ctrl+3, Ctrl+4: on every page the sidebar shows the red dot with the elapsed
   time and a red banner "Recording hh:mm:ss — open the recorder"; its **Recorder** link goes
   back. Pause (two bars button): the dots turn amber and the timer freezes; resume.
6. Speak for about a minute, then press the round stop button (no question asked). Wait for the
   "Minutes are ready" toast (bottom right) and dismiss it.
7. Meetings: the new row shows `Phase 35 manual check` above its date; the detail heading shows
   the title with the date under it. The session's `session.json` has
   `"title": "Phase 35 manual check"`; the minutes read in context of that title.
8. Export Word and open the `.docx`: the document title is `Phase 35 manual check` and the first
   detail line is `Date: <yyyy-MM-dd HH:mm>`.
9. Rename after the fact through the API (PowerShell):
   `Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:8765/sessions/<id> -ContentType application/json -Body '{"title": "Renamed"}'`
   returns the summary with `title: Renamed`; Meetings → Refresh shows it. A 201-character
   title returns `422 title_too_long`.
10. Config → Desktop app → Interface language → Português: the sidebar reads Gravador, Reuniões,
    Perguntar, Configurações and the title box "Sobre o que é esta reunião?"; switch back.
11. Ask: ask about the meeting; click a source: the app switches to Meetings and opens that
    meeting at the cited line.

### Decisions and notes

- Runs in parallel with phase 31 (SQLite backend): the engine part stays additive. The title is a
  `session.json` field written through the phase 30 `SessionRepository` port
  (`read_meta` / `write_meta`), and the shared contract suite checks it round-trips, so the SQLite
  backend picks it up.
- Titles are trimmed and whitespace runs (new lines too) collapse into one space; blank = untitled
  (null). Longer than 200 characters → `422 title_too_long`.
- `PATCH` of the session being recorded or finalized goes through its own `SessionMeta` (it keeps
  rewriting `session.json` until done, so a direct write would be lost); any other session is
  rewritten through the repository. A session being recovered → `409 session_being_recovered`.
- UI split: `MainViewModel` stays the `MainWindow` DataContext (engine connection and events,
  notifications, recovery, tray, interface language, window size), because every view binds its
  strings through `$parent[Window].((vm:MainViewModel)DataContext).L[...]`. Recording moved to
  `RecorderPageViewModel`; the shared state (state, elapsed, session id, title) is
  `RecordingSessionService`. Existing tests reach the recorder through `viewModel.Recorder`.
- Title while recording: sent once typing pauses for 800 ms, at once on Enter, and before Stop;
  cleared when the recording ends (the next meeting starts untitled; rename the old one later). A
  failed start keeps the typed title. Editable while idle, recording or paused (not while starting
  or finalizing).
- Shell: `NavItem` per page (key, label, `Icon.*` resource, `Ctrl+N` gesture, page ViewModel);
  `NavigateCommand` takes the page key. `IsRecordingElsewhere` drives a "Recording 00:12:03 —
  open the recorder" banner over the other pages (on top of the sidebar dot and time). A source on
  the Ask page switches to Meetings, then opens the meeting there. The sidebar theme button
  (`AppearanceViewModel.ToggleCommand`) flips light ↔ dark from what is shown now
  (`IThemeService.IsDark`). `ui.json` gains `sidebar_collapsed`.
- Views: the shell is `Views/ShellView.axaml` (a `UserControl` inside `MainWindow`), not
  `ShellWindow.axaml`, because `MainWindow` stays the only window. The Ask page reuses `AskView`
  (now a page, no longer an expander under the history). The interface language picker moved
  from the start screen to Config → Desktop app; the bottom status bar is gone (engine status in
  the sidebar, health on the Config page). The recorder page has its own `L` because flyouts are
  popups without a window ancestor. The meeting title shows in the history list and the detail
  heading (date under it); renaming a past meeting in the UI is left to phase 37 (the engine
  already supports it).
- The resx strings for the whole phase (nav labels, placeholder, untitled, sidebar, tray) were
  added in the title commit. `Untitled` is not shown yet (untitled meetings show their date); it
  is there for the phase 36 list. The old `TabRecording` / `TabHistory` / `TabSettings` keys were
  removed.
- Tray tooltip: `TrayToolTipTitled` ("VozAta — {state}: {title}") while the recording has a title.
