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
