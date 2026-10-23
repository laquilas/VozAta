# Phase 48 — Minutes So Far Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** While recording, **Minutes so far** writes minutes of what was said until now without stopping; every such result (and, from phase 49, minutes of a time range) is kept on the meeting in a **Partial minutes** list, apart from the final minutes.

**Architecture:** Live segments are already stored as they are committed, so partial minutes use the same path as regenerated minutes: load the best transcript, keep the segments of the range, run `MinutesGenerator` with a scope line, store the result. A `PartialMinutesJob` (like `AskJob`, outside the queue, Ask GPU priority) runs it; routes under `/sessions/{id}/partial-minutes`; event `partial_minutes_ready`.

**Spec:** `docs/roadmap/phases/48-minutes-so-far.md`.

## Rulings

- **Storage**: `PartialMinutes(id, created_at, start, end, origin, template, markdown)` in `domain.py`; port `read_partial_minutes(session_id) -> list[PartialMinutes]` (oldest first) and `write_partial_minutes(session_id, items)` (replace all). SQLite migration `005_partial_minutes.sql` (rows, `ON DELETE CASCADE`); files backend `partial_minutes.json` `{items: [...]}`. Bundle export / import and the folder migration carry them.
- **Range**: `segments_in_range(segments, start, end)`: a segment belongs when `start <= segment.start < end` (`end` None = up to the last segment). `start` / `end` stored are the requested ones (`end` None replaced by the last segment's end).
- **Scope line** (new locale keys, three languages): `minutes.scope_live` "The meeting is still in progress: these minutes cover what was said up to {end}; do not invent an outcome for what is still open." and `minutes.scope_range` "These minutes cover only the part of the meeting from {start} to {end}."; times `hh:mm:ss`. Passed like the title to every prompt (`minutes_prompt`, `map_prompt`, `reduce_prompt`).
- **Service**: `minutes/partial_minutes.py` `write_partial_minutes(store, session_id, build_generator, labeler, *, start, end, origin, template, live, new_id, now) -> PartialMinutes`; language / vocabulary / title / speaker names as `write_session_minutes`; `EmptyTranscriptError` for an empty range.
- **Job**: `api/partial_minutes_job.py` `PartialMinutesJob(build_generator, store, labeler, broadcaster, localizer, gate, uses_gpu)`: `start(session_id, start, end, origin, template, live) -> str | None` (None when busy); thread; `GpuGate.priority(ASK)` when the LLM is on the local GPU; events `partial_minutes_ready {partial_id, start, end, origin}` or `error` (`empty_range`, `partial_minutes_failed`, `llm_unreachable`). The generator comes from the container's `minutes_generator` factory (frees a kept Whisper only when no recording uses it).
- **Routes** (`api/routes/partial_minutes.py`): `POST /sessions/{id}/partial-minutes {start?, end?, template?}` → 202 `{partial_id}`; recording session: allowed when live transcription is on (else 409 `live_transcription_off`), `live` scope, origin `button`; other sessions: origin `range`; 409 `partial_minutes_in_progress`; 404 unknown session. `GET /sessions/{id}/partial-minutes` → `{items: [{id, created_at, start, end, origin, template}]}` (no Markdown); `GET .../{pid}` → full item; `DELETE .../{pid}` → 204.
- **UI**: client methods and DTOs; event `PartialMinutesReadyEvent`; recorder **Minutes so far** button (enabled while recording and the session has live transcription, not while one is being written) and a side panel with the Markdown, Copy and Close; meeting page **Partial minutes** tab: list, view, copy, delete; refreshed on the event.

## Tasks

### Task 1: Storage of partial minutes
- [x] Domain type, port, SQLite migration + annotations, files backend, folder writer / reader / migration; tests for both backends; commit `feat(storage): keep partial minutes on a meeting`.

### Task 2: Range, scope line and the service
- [x] `segments_in_range`, scope keys, prompts / generator `scope`, `write_partial_minutes`; tests; commit `feat(minutes): write minutes of part of a meeting`.

### Task 3: Job, routes, events
- [x] `PartialMinutesJob`, routes, container wiring, error locales, contract docs; tests; commit `feat(api): minutes so far while recording`.

### Task 4: Desktop
- [x] Client + event, recorder button and panel, meeting page tab, RESX; tests; commit `feat(ui): minutes so far and the partial minutes tab`.

### Task 5: Docs, suites, manual check, phase done
- [x] User guide, `architecture.md` (data model, port), full suites, manual check (scratch engine, a TTS meeting played while recording, Minutes so far, Stop, final minutes separate); PR.
