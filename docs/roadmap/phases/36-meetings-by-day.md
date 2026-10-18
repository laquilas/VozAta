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
- **Next step:** `ViewModels/MeetingsPageViewModel.cs` (own file; drop the stub from `Pages.cs`):
  weeks, day groups, totals, week navigation, infinite scroll, live row, with
  `MeetingsPageViewModelTests.cs`.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Repository: `list_range`, `speaker_count`, `delete` (both backends, contract suite; files
      go to the Recycle Bin through a `Recycler` port)
- [x] API: `GET /sessions?from=&to=` grouped by local day; `SessionSummary` gains
      `speaker_count`, `has_action_items`, `template`
- [x] API: `DELETE /sessions/{id}` (`204`, `409` while recording, search index cleared)
- [x] UI client: range and delete calls, new summary fields (`ListSessionDaysAsync`,
      `DeleteSessionAsync`, `VozAta.Client/Meetings.cs`, `Fakes/FakeEngineClient.Meetings.cs`)
- [ ] UI: `MeetingsPageViewModel` (weeks, day groups, totals, navigation, infinite scroll, live row)
- [ ] UI: inline rename, delete with confirmation and undo, search filtering, row actions
- [ ] UI: `MeetingsPage.axaml`, strings in en / pt-BR / es, headless screenshots
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
- Local days use the engine machine's time zone (`datetime.astimezone()`, DST aware); the UI and
  engine run on the same machine.
