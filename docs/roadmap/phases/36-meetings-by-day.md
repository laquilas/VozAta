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

- [x] Engine tests: range query and totals (time zones, midnight), delete cascade, delete while
      recording → 409, Recycle Bin path for files (fake).
- [x] UI tests: grouping, totals, week navigation, infinite scroll, rename, delete confirm/undo,
      search filtering, live row pinned.
- [ ] Manual: with a week of meetings (migrated or recorded), the list matches Toggl's layout;
      rename, delete and play work. Screenshots light and dark in the PR. — *pending manual (user,
      on the reference machine; recipe in Progress). Headless light/dark renders of the page are
      produced by `ThemeRenderTests` and attached to the PR.*
- [x] Resource parity test passes.

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
- **Status:** ready for PR
- **Updated:** 2026-10-17 23:15
- **Next step:** the user runs the manual check recipe below on the reference machine, attaches
  real screenshots if wanted, and merges the PR.

### Steps

- [x] Start the phase (README status, Progress) — `5a98709`
- [x] Repository: `list_range`, `speaker_count`, `delete` (both backends, contract suite; files
      go to the Recycle Bin through a `Recycler` port) — `1a5422c`
- [x] API: `GET /sessions?from=&to=` grouped by local day; `SessionSummary` gains
      `speaker_count`, `has_action_items`, `template` — `6fcecba`
- [x] API: `DELETE /sessions/{id}` (`204`, `409` while recording, search index cleared) —
      `96b7ad9`, architecture `526706d`
- [x] UI client: range and delete calls, new summary fields (`ListSessionDaysAsync`,
      `DeleteSessionAsync`, `VozAta.Client/Meetings.cs`, `Fakes/FakeEngineClient.Meetings.cs`) —
      `186e3f4`
- [x] UI: `MeetingsPageViewModel` (weeks, day groups, totals, navigation, infinite scroll, live
      row), inline rename, delete with confirmation and undo, search filtering, row actions —
      `4b51ad8`
- [x] UI: `MeetingsPage.axaml`, strings in en / pt-BR / es, headless screenshots — `0a0859d`
- [x] Full suites (engine 1457 passed, 3 deselected, 99 % coverage, new modules 100 %; UI 560
      passed), `ruff check` / `ruff format --check`, `dotnet format --verify-no-changes`,
      acceptance criteria, PR
- [ ] Manual check on the reference machine — pending manual (user), recipe below

### Manual check recipe

No microphone, speakers or GPU were used by the agent; run this on the reference machine, one
phase at a time, after `git checkout feature/36-meetings-by-day`.

1. Install the new dependency: `.venv/Scripts/python -m pip install -e "engine[dev]"`
   (adds `Send2Trash`). Build the UI: `dotnet build ui/VozAta.sln`.
2. **File backend** — copy `engine/recordings` to a scratch folder (e.g. `C:\temp\vozata-36`),
   then in `engine/.env` set `STORAGE_BACKEND=files` and `OUTPUT_DIR=C:\temp\vozata-36`.
   Start the app: `dotnet run --project ui/src/VozAta.Desktop`; press Ctrl+2 (Meetings).
   - Header: ◀ ▶, "This week" and its `h:mm:ss` total, the search box, refresh.
   - Day cards newest first ("Today", "Yesterday", "Wed, 14 Oct"…) with the day total on the
     right; rows: title (or grey "Untitled meeting"), template and language pills, people icon
     with the diarized speaker count, start–end time, duration right-aligned.
   - Scroll down: older weeks load ("Last week", "6 Oct – 12 Oct"…) until no
     "Load older meetings" button is left. ◀ / ▶ / "This week" move a week at a time.
   - `curl "http://127.0.0.1:8765/sessions?from=<monday>&to=<sunday>"` shows the same days and
     totals; `storage` is `files`.
3. **Rename** — hover a row → pencil → type a title → Enter: the row shows it, and it is still
   there after refresh (`session.json.title`). Pencil → Esc: nothing changes. A blank title makes
   it "Untitled meeting" again.
4. **Delete (files)** — hover → trash: the dialog says the meeting goes to the Recycle Bin →
   Delete → the row disappears and a toast "… moved to the Recycle Bin. Undo" appears bottom
   left. Click Undo: the row is back and its folder is still in `OUTPUT_DIR`. Delete again and
   wait 8 s: the folder is gone from `OUTPUT_DIR` and is in the Windows Recycle Bin (restore it
   from there to undo the test).
5. **Delete (SQLite)** — set `STORAGE_BACKEND=sqlite` (default database, or `DATABASE_PATH` to a
   scratch file), restart the app, delete a test meeting: the dialog says it is permanent, there
   is no Undo, `GET /sessions/<id>` answers 404 and its audio folder is gone.
6. **Play / export** — hover → ▶ opens `mixed.wav` in the default player (a meeting without a
   mix shows "This meeting has no mixed recording to play."); hover → export icon → "Export
   Word" → the save dialog → the file opens in Word.
7. **Search** — type a word that was said: the weeks are replaced by the matching meetings (title,
   date · duration) with their snippets; clicking a snippet opens the detail on the right at that
   line; clearing the box brings the weeks back.
8. **Live row** — start a short test recording on the Recorder page (your consent; any
   devices), go to Meetings: the recording is pinned on top with a pulsing red dot and the running
   time, without a trash button; `curl -X DELETE http://127.0.0.1:8765/sessions/<live id>`
   answers `409 session_still_active`. Stop it; after finalizing it moves into "Today".
9. **UI Automation** — with Accessibility Insights / Inspect, the row actions are named "Play
   the recording", "Export", "Rename", "Delete" (also while faded), the export formats "Export
   Markdown / Word / PDF", the title box "Meeting title (Enter saves, Esc cancels)", the toast
   "Undo" / "Dismiss", the header "Previous week" / "Next week", and the confirm dialog buttons
   have automation ids `ConfirmYes` / `ConfirmNo`.
10. **Languages** — Config → interface language pt-BR, then es: "Esta semana" / "Hoje" / "Hoy",
    weekday and month names follow the language, and so do the dialog and toast texts.
11. Restore `engine/.env` (`STORAGE_BACKEND`, `OUTPUT_DIR`) afterwards.

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
