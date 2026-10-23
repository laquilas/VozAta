# Phase 49 — Minutes of a Time Range Implementation Plan

**Goal:** On a recorded meeting, write minutes of a part only (e.g. 00:02:32–00:12:54), typing the times or taking them from the player or a transcript line; the result joins the Partial minutes list (phase 48).

**Spec:** `docs/roadmap/phases/49-minutes-of-a-range.md`.

## Rulings

- Engine: the phase 48 route already writes ranges; `422 invalid_range` also when the range starts at or ends after the recorded length (`duration_seconds` + 1 s tolerance), for meetings not being recorded.
- `TimeText.TryParse("hh:mm:ss" | "h:mm:ss" | "mm:ss" | "ss")`: minutes and seconds below 60; the inverse of `TranscriptLine.FormatTime`.
- `RangeMinutesViewModel` (meeting page, finished meetings): `From` / `To` text, validation message (`RangeInvalidTime`, `RangeEndBeforeStart`, `RangeBeyondEnd`), `Generate` (the page's template), "use the player position" for each box, `StartAt(line)` / `EndAt(line)` from a transcript line (`TranscriptLine.End` added). While written: busy; on `partial_minutes_ready` of this meeting the Partial minutes tab opens with it; the error codes end it.
- UI: a bar on top of the Partial minutes tab; "Start here" / "End here" in the transcript line's context menu.

## Tasks

- [x] Task 1: engine length check, tests; commit `feat(api): refuse a range beyond the recorded length`.
- [x] Task 2: `TimeText`, `RangeMinutesViewModel`, page wiring, views, RESX, tests; commit `feat(ui): minutes of a part of a recorded meeting`.
- [x] Task 3: docs, full suites, manual check, phase done, PR.
