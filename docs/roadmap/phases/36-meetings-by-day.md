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
