# Phase 18 — Echo dedupe

## Goal

When the user is not wearing headphones, the microphone also captures the remote participants from
the speakers and their words appear twice (as `Me` and as `Others`). Detect and drop those echoed
mic segments.

## Depends on

05, 27 (pause-based chunks make echoed phrases line up)

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §6 (data flow — `EchoFilter` sits between worker and sinks),
  §8 (segment schema), §9 (keys)

## Scope

| File | Content |
|------|---------|
| `transcription/echo.py` | `EchoFilter(similarity_threshold, hold_seconds, tolerance=1.0, clock)`: keeps system segments from the last 30 s; holds each mic segment for `hold_seconds` (so the matching system segment can arrive), then compares it with system segments overlapping in time (± tolerance) using normalized text similarity (`difflib.SequenceMatcher` on lowercased, punctuation-free text, or `rapidfuzz` if added); drops it when similarity ≥ `ECHO_SIMILARITY` |
| `transcription/worker.py` / `session.py` | insert the filter before the sinks when `ECHO_DEDUPE_ENABLED`; `flush()` at stop releases held segments |
| `session.json` | counter `echo_dropped` |
| `config.py`, `.env.example` | `ECHO_DEDUPE_ENABLED` (`true`), `ECHO_SIMILARITY` (`0.85`), `ECHO_HOLD_SECONDS` (default `CHUNK_SECONDS + 3`) |

## Design notes

- Holding mic segments adds latency only to the mic channel; document it.
- Partial echo (the user talks over the remote speaker) is kept when similarity is below the
  threshold — prefer keeping text over losing it.

## Acceptance criteria

- [x] Tests (fake clock): identical text overlapping → dropped; different text → kept; matching
      text outside the time window → kept; system segment arriving later within hold → dropped;
      `flush()` releases held segments; counter updated.
- [ ] Manual: record without headphones while a video plays → `Me` lines with the video's speech
      are gone; own speech still appears. *Pending manual (shared audio hardware): recipe in
      Progress.*
- [x] Coverage ≥ 80 % (engine total 100 %, `echo.py` 100 %).

## Tests

`tests/transcription/test_echo.py`, `tests/test_session.py` (extended).

## Out of scope

Acoustic echo cancellation on the audio signal (backlog).

## Kickoff prompt

> Execute phase 18 of the roadmap (`docs/roadmap/phases/18-echo-dedupe.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/18-echo-dedupe`
- **Status:** ready for PR
- **Updated:** 2026-10-17 12:00
- **Next step:** run the manual check recipe below on the reference machine (alone, no other
  phase using the audio hardware), then merge the PR.

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `EchoFilter` in `transcription/echo.py` with fake-clock tests
- [x] Config keys `ECHO_DEDUPE_ENABLED`, `ECHO_SIMILARITY`, `ECHO_HOLD_SECONDS` (config, fields,
      `.env.example`, UI labels, architecture §9)
- [x] Wire the filter in front of the sinks (worker tick, pipeline, `flush()` at stop) and write
      `session.json.echo_dropped` (architecture §6 / §8)
- [x] Acceptance criteria, README `done`, PR
- [ ] Manual check (pending: shared audio hardware)

### Decisions and notes

- `EchoFilter` is a `TranscriptSink` decorator (it wraps the composite sink) and takes the hold
  clock (`time.monotonic` by default) plus an `on_dropped` callback. The hold runs from the
  moment the mic segment reaches the filter, not from its session time.
- Similarity is `echo_score`: the share of the mic words found, in order, in the system words
  (`difflib.SequenceMatcher` on word lists of lowercased, punctuation-free text). It is compared
  with the system **words** spoken within the mic segment's span ± tolerance (whole segments when a
  segment has no word timings). Word level rather than character level: a short mic phrase would
  otherwise "match" scattered letters of a longer system text. Asymmetric, so an echo split across
  two system segments or cut out of a longer one still scores 1, while talking over the remote
  speaker adds unmatched mic words and keeps the segment.
- `ECHO_HOLD_SECONDS` is optional (`Settings.echo_hold_seconds: float | None`); empty means
  `CHUNK_SECONDS + 3`, resolved by `Settings.effective_echo_hold_seconds`, so saving the settings
  page does not freeze the derived value. The keys live in the `transcription` settings group.
- "Engine only" exception: the UI test `Every_engine_setting_has_a_label_and_help_text` requires a
  `Setting_*` / `SettingHelp_*` string for every `.env.example` key, so the three `Strings*.resx`
  files got labels for the new keys (no UI code changes).
- Wiring: `CapturePipeline` wraps its `CompositeSink` in `EchoFilter` when enabled;
  `TranscriptionWorker` got an optional `tick` hook (run on the transcription thread after every
  chunk and idle wait) that releases expired holds, so the filter needs no thread of its own.
  `drain()` closes the filter, which flushes held segments. `RecordingSession._drain()` then
  writes `echo_dropped` through `SessionMeta.echo_dropped()` (absent when the filter is off).
- A dropped mic segment sends an empty mic `partial` (when `LIVE_PARTIALS`), because the worker
  had already forgotten the interim text the segment was meant to replace.
- Known limit: interim text (phase 28) is not deduplicated, so echoed speech can still flash as a
  mic partial until the segment is dropped.

### Manual check recipe (run alone, before merge: needs speakers and a microphone)

1. From `engine/`, with the default `.env` (`ECHO_DEDUPE_ENABLED=true`), **no headphones**,
   speakers at a normal volume: `../.venv/Scripts/python -m vozata record`.
2. Play a video with clear speech (e.g. a news clip) for ~60 s and stay silent.
3. Then, with the video paused, say two sentences of your own; resume the video and talk over it
   for one sentence.
4. Stop with Ctrl+C. Expected in the console and in `transcript.md`: the video's speech appears
   only as the system label (`Others`); your own sentences appear as `Me` (about
   `CHUNK_SECONDS + 3` s late); the sentence spoken over the video is kept.
5. `session.json` has `"echo_dropped": N` with N > 0.
6. Repeat with `ECHO_DEDUPE_ENABLED=false` and confirm the video's speech appears twice (`Me` and
   `Others`) and `session.json` has no `echo_dropped` key.
