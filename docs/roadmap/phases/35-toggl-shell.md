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

- [ ] ViewModel tests: navigation, shortcuts, recording indicator visible on every page, title
      sent on start and patched while recording, Enter starts, chips disabled while recording
      (except title).
- [ ] Engine tests: `title` validation, PATCH while recording and after, title in summary,
      minutes prompt and export.
- [ ] Manual: record a meeting with a title from the new timer bar, navigate between pages while
      recording, stop; title shows in history, minutes and the exported docx. Screenshots light
      and dark in the PR.
- [ ] Resource parity test passes.

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
- **Status:** in progress
- **Updated:** 2026-10-17 21:37
- **Next step:** UI — `RecordingSessionService` (shared state) and `RecorderPageViewModel` split
  out of `MainViewModel` (title, Enter starts, chips locked while recording);
  `RecorderPageViewModelTests.cs`.

### Steps

- [x] Engine: `title` on start, in `session.json` and `SessionSummary`; contract suite — `9b1a671`
- [x] Engine: `PATCH /sessions/{id}` `{title}` while recording and after — `fc66b75`
- [x] Engine: title in the minutes prompt (en / pt-BR / es) and as the export document title —
      `2956745`, `dd74ba4`
- [x] Docs: api-contract, architecture §8
- [x] Docs — `3ee4679`
- [x] UI client: `Title` on start and in `SessionSummary`, `UpdateSessionTitleAsync`
- [ ] UI: `RecordingSessionService` + `RecorderPageViewModel` split out of `MainViewModel`
- [ ] UI: `ShellViewModel` (pages, navigation, Ctrl+1…4, sidebar collapse in `ui.json`) and the
      Meetings / Ask / Config page ViewModels
- [ ] UI: shell view (sidebar, toasts, recovery banner) and the recorder page timer bar; tray
      tooltip with the title; strings in en / pt-BR / es
- [ ] UI: headless renders of the new shell (idle and recording, light and dark)
- [ ] Full suites, acceptance criteria, PR

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
