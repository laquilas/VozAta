# Phase 49 — Minutes of a time range

## Goal

On a recorded meeting the user writes minutes of a part only — e.g. from 00:02:32 to 00:12:54 —
by typing the times or taking them from the player. The result joins the meeting's Partial
minutes list (phase 48).

## Depends on

48

## Read first

- `ui/CLAUDE.md`, [phase 48](48-minutes-so-far.md), [phase 37](37-detail-and-player.md)
- `SessionPageViewModel.cs`, `SessionPage.axaml`, `PlayerBarViewModel.cs`, `Models.cs`
  (`TranscriptLine.FormatTime`), `api/routes/partial_minutes.py`

## Scope

**UI (meeting page, finished meetings)**

- **Minutes of a part**: From / To boxes in `hh:mm:ss` (`mm:ss` also accepted), a "use the player
  position" button for each box, the template picker, Generate.
- `TimeText.TryParse` (new), the inverse of `TranscriptLine.FormatTime`.
- Validation `0 ≤ from < to ≤ duration` with localized messages; Generate disabled until valid.
- Shortcut: "Start here" / "End here" on a transcript line sets the boxes from the line's start
  and end.
- The result lands in the Partial minutes tab (origin `range`), which opens.

**Engine**: the phase 48 route already takes `start` / `end`; this phase adds 422 `invalid_range`
(`start ≥ end`, negative, beyond the audio length) and the `range` origin when both are given for
a finished meeting.

**Docs**: `api-contract.md` (`invalid_range`), user guide.

## Acceptance criteria

- [x] On a finished meeting, minutes of 00:02:32–00:12:54 cover only that part and appear in the
      Partial minutes list with the range.
- [x] Invalid times are refused with a clear message, in the UI and in the API.

## Tests

UI: parser (valid, `mm:ss`, out of range, garbage), validation, player-position buttons, line
shortcuts, command enablement, client call shape, resource parity. Engine: `invalid_range` cases,
origin.

## Out of scope

Several ranges at once, a waveform selector, trimming the audio.

## Kickoff prompt

> Start phase 49 (`docs/roadmap/phases/49-minutes-of-a-range.md`) once phase 48 is merged: read its
> *Read first* files, write `plans/49-minutes-of-a-range.md`, then implement it task by task.

## Progress

- **Branch:** `feature/49-minutes-of-a-range`
- **Status:** ready for PR
- **Updated:** 2026-10-22
- **Next step:** open the PR to `main`; then phase 50 (`docs/roadmap/phases/50-voice-commands.md`).

### Steps

- [x] Implementation plan (`plans/49-minutes-of-a-range.md`)
- [x] Engine: refuse a range beyond the recorded length
- [x] Desktop: Minutes of a part (From / To, player position, line shortcuts)
- [x] Docs, full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR; GitHub Actions is disabled, every check runs locally.
- The line shortcut is a small ⋯ button with a menu on each transcript line (the selectable text
  keeps its own copy menu), not a right-click.
- Manual check (2026-10-22): on the meeting recorded in the phase 48 check (68 s, local Ollama),
  `POST .../partial-minutes {start: 14, end: 41}` wrote minutes of that part only in 22 s (origin
  `range`, 14–41): the beta moved to Tuesday, no Carlos task and no macOS question (said outside
  the part). A part after the end answered 422 with the end-before-start message, so it got its own
  code `range_beyond_end` naming the length. The desktop bar and panel were checked in the headless
  renders (`session-partial-minutes-*.png`, `recorder-minutes-so-far-*.png`, light and dark).
