# Phase 36 — Meetings list grouped by day

## Goal

Show meetings the way Toggl Track shows time entries: grouped by day with a day total, a week
total on top, compact rows with title, tags and duration, and quick actions on hover.

## Depends on

35, 31

## Read first

- `ui/CLAUDE.md`, `engine/CLAUDE.md`
- [phase 35](35-toggl-shell.md) (shell, title), [phase 31](31-sqlite-database.md) (repository)
- [api-contract.md](../api-contract.md) — `GET /sessions`, `GET /search`
- `Views/HistoryView.axaml`, `ViewModels/HistoryViewModel.cs`, `ViewModels/SearchViewModel.cs`

## Scope

**Engine**

| File | Content |
|------|---------|
| API | `GET /sessions?from=&to=` (ISO dates, local time zone) returns `{days: [{date, total_seconds, items: [SessionSummary]}], total_seconds}` newest first; the paged form stays for compatibility. `SessionSummary` gains `speaker_count`, `has_action_items`. `DELETE /sessions/{id}` → `204` (deletes the row, segments, audio, minutes; `409` while recording; file backend deletes the folder to the Recycle Bin via `send2trash`, never permanently) |
| Repository | `list_range(from, to)`, `delete(id)` in both backends |

**UI**

| File | Content |
|------|---------|
| `Views/MeetingsPage.axaml` | header: "This week" total, week navigation (◀ ▶, "This week"), search box. Day groups: header with weekday + date and the day total on the right. Rows: title (or "Untitled meeting" in secondary text), tags (template, language pills), speaker count icon, start–end time, duration right-aligned; live session pinned at the top with a pulsing dot. Hover/selection shows icon buttons: play (mixed), export, delete. Click opens the detail (phase 37; until then the existing detail view on the right) |
| `ViewModels/MeetingsPageViewModel.cs` | loads one week at a time, infinite scroll backwards loads the previous week; inline title rename (Enter saves via `PATCH`, Esc cancels); delete with a confirmation dialog and an "Undo" toast for the file backend; search reuses `SearchViewModel` and filters to matching meetings with snippets |
| Resources | strings in en / pt-BR / es (weekday names via `CultureInfo`, not resx) |

## Design notes

- Durations format as `h:mm:ss` like Toggl; day and week totals use the same format.
- Grouping uses the session's local start date; a meeting crossing midnight stays on its start day.
- Delete is permanent for sqlite sessions (after confirmation) — note it in the dialog text.

## Acceptance criteria

- [ ] Engine tests: range query and totals (time zones, midnight), delete cascade, delete while
      recording → 409, Recycle Bin path for files (fake).
- [ ] UI tests: grouping, totals, week navigation, infinite scroll, rename, delete confirm/undo,
      search filtering, live row pinned.
- [ ] Manual: with a week of meetings (migrated or recorded), the list matches Toggl's layout;
      rename, delete and play work. Screenshots light and dark in the PR.
- [ ] Resource parity test passes.

## Tests

`tests/api/test_sessions_range.py`, `tests/api/test_session_delete.py`,
`MeetingsPageViewModelTests.cs`.

## Out of scope

Calendar/reports view, tags beyond template and language, bulk actions.

## Kickoff prompt

> Execute phase 36 of the roadmap (`docs/roadmap/phases/36-meetings-by-day.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/36-meetings-by-day`
- **Status:** in progress
- **Updated:** 2026-10-17 22:40
- **Next step:** run the full engine and UI suites, `ruff`, `dotnet format`; tick the acceptance
  criteria, set the README status to `done`, write the manual check recipe, open the PR.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Repository: `list_range`, `speaker_count`, `delete` (both backends, contract suite; files
      go to the Recycle Bin through a `Recycler` port)
- [x] API: `GET /sessions?from=&to=` grouped by local day; `SessionSummary` gains
      `speaker_count`, `has_action_items`, `template`
- [x] API: `DELETE /sessions/{id}` (`204`, `409` while recording, search index cleared)
- [x] UI client: range and delete calls, new summary fields (`ListSessionDaysAsync`,
      `DeleteSessionAsync`, `VozAta.Client/Meetings.cs`, `Fakes/FakeEngineClient.Meetings.cs`)
- [x] UI: `MeetingsPageViewModel` (weeks, day groups, totals, navigation, infinite scroll, live row)
- [x] UI: inline rename, delete with confirmation and undo, search filtering, row actions
- [x] UI: `MeetingsPage.axaml`, strings in en / pt-BR / es, headless screenshots
- [ ] Full suites, acceptance criteria, PR

### Decisions and notes

- `speaker_count` counts the speakers diarization found (`system:<n>`); a renamed `mic` does not
  count. 0 before diarization.
- `FileSessionRepository(store, recycler)`: the recycler is optional so the CLI and tests that
  never delete keep working; `delete` without one raises. `bootstrap` passes
  `Send2TrashRecycler` (new dependency `Send2Trash`). Unit tests use `FakeRecycler`, which moves
  folders into a `tmp_path` "recycle bin" — never the real one.
- SQLite `delete` is permanent: the rows (cascade, the FTS index follows) and the audio folder.
- Range response extras (additive, in api-contract): `has_earlier` (stops infinite scroll without
  probing empty weeks forever) and `storage` (the UI words the delete dialog and offers "Undo"
  only for the file backend). Both dates are required (`422 invalid_date_range`). Days without
  meetings are left out. `SessionSummary` also gains `template` (the template pill of a row).
- Weeks start on Monday (ISO, like Toggl's default). Day labels: "Today", "Yesterday", else
  `ddd, d MMM` in the UI language's culture; week labels "This week", "Last week", else
  "d MMM – d MMM". Durations and totals `h:mm:ss`.
- Undo for the file backend is a deferred delete: the row is hidden and `DELETE` is sent when the
  8 s undo window ends (or at once on a second delete, closing the toast, or closing the app).
  Restoring from the Recycle Bin programmatically was not attempted. SQLite deletes at once after
  the dialog (which says it is permanent); a toast confirms it, without Undo.
- Infinite scroll skips up to 26 empty weeks per load; `has_earlier` stops it.
- `MeetingsPageViewModel` keeps `HistoryViewModel` for the detail on the right (until phase 37),
  for the Ask page citations and for search (`SearchViewModel` is reused as is). Search matches
  of meetings outside the loaded weeks are completed with `GET /sessions/{id}`.
- Row actions: play (mixed WAV via `GET /sessions/{id}` folder + files), export (an inline strip
  with Markdown / Word / PDF — no flyout, so UI Automation reaches it), rename, delete.
- View: `Views/MeetingsPage.axaml` replaces `HistoryView` (removed); the detail moved unchanged
  into `Views/SessionDetailView.axaml`, shown in a 460 px column on the right only while a
  meeting is open (the list uses the full width otherwise). Row actions fade in over the times on
  hover, selection or keyboard focus (`Opacity` + `IsHitTestVisible`, so UI Automation still
  sees them); every button, the title box, the export formats, the undo toast and the confirm
  dialog buttons (`ConfirmYes` / `ConfirmNo` automation ids) have `AutomationProperties.Name`.
  Older weeks load through `Views/InfiniteScroll.cs` (attached to the `ScrollViewer`) and a
  "Load older meetings" button. New icons `Icon.Edit`, `Icon.People` (Fluent, MIT).
- Local days use the engine machine's time zone (`datetime.astimezone()`, DST aware); the UI and
  engine run on the same machine.
