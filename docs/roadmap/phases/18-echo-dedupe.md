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

- [ ] Tests (fake clock): identical text overlapping → dropped; different text → kept; matching
      text outside the time window → kept; system segment arriving later within hold → dropped;
      `flush()` releases held segments; counter updated.
- [ ] Manual: record without headphones while a video plays → `Me` lines with the video's speech
      are gone; own speech still appears.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/transcription/test_echo.py`, `tests/test_session.py` (extended).

## Out of scope

Acoustic echo cancellation on the audio signal (backlog).

## Kickoff prompt

> Execute phase 18 of the roadmap (`docs/roadmap/phases/18-echo-dedupe.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/18-echo-dedupe`
- **Status:** in progress
- **Updated:** 2026-10-17 10:30
- **Next step:** add `ECHO_DEDUPE_ENABLED`, `ECHO_SIMILARITY`, `ECHO_HOLD_SECONDS` to
  `config.py`, `settings_fields.py`, `engine/.env.example`, the three UI `Strings*.resx` and
  architecture §9 (tests in `tests/test_config.py`).

### Steps

- [x] Start the phase (README status, Progress section)
- [x] `EchoFilter` in `transcription/echo.py` with fake-clock tests
- [ ] Config keys `ECHO_DEDUPE_ENABLED`, `ECHO_SIMILARITY`, `ECHO_HOLD_SECONDS` (config, fields,
      `.env.example`, UI labels, architecture §9)
- [ ] Wire the filter in front of the sinks (worker tick, pipeline, `flush()` at stop) and write
      `session.json.echo_dropped` (architecture §6 / §8)
- [ ] Acceptance criteria, README `done`, PR

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
