# Phase 28 — Live interim text

## Goal

Show provisional text while someone is still speaking, replaced by the committed segment. Origin:
[optimizations.md](../optimizations.md) O3.

## Depends on

27, 07

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [optimizations.md](../optimizations.md) — O3
- [api-contract.md](../api-contract.md) — `partial` event

## Scope

| Item | Content |
|------|---------|
| `transcription/worker.py` | when the chunk queue is empty, transcribe a channel's **uncommitted** audio (VAD buffer or stitcher carry) at most once per `PARTIAL_INTERVAL_SECONDS` and only with ≥ 1 s of speech; never re-transcribe committed audio |
| `ports.py` / `SessionObserver` | `on_partial(channel, speaker_id, start, text)` |
| API | `partial` event `{channel, speaker_id, label, start, text}`; empty `text` clears it; not written to files |
| `config.py`, `.env.example` | `LIVE_PARTIALS` (`true`), `PARTIAL_INTERVAL_SECONDS` (1.5) |
| UI | one grey italic line per channel below the transcript, replaced in place and removed when the segment arrives |

## Design notes

- Partials must never delay committed transcription: skip them whenever chunks are queued.
- Partials are not used for minutes, search or echo dedupe.

## Acceptance criteria

- [ ] Worker tests (fake transcriber/clock): partial only when idle, interval respected, cleared on
      commit, committed audio never re-sent.
- [ ] API/WebSocket test: `partial` envelope; ViewModel test: line replaced then removed.
- [ ] Manual: text appears while speaking a long sentence and is replaced by the final line.
- [ ] Coverage ≥ 80 % (engine and UI).

## Tests

`tests/transcription/test_worker.py`, `tests/api/test_ws.py`, `MainViewModelTests.cs`.

## Out of scope

Partials in the CLI console.

## Kickoff prompt

> Execute phase 28 of the roadmap (`docs/roadmap/phases/28-live-partials.md`), following
> `docs/roadmap/README.md`.
