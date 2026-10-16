# Phase 05 — Session and CLI (MVP)

## Goal

Wire everything into a recording session with a command-line interface: start, live transcript in
the terminal, pause/resume, stop with the fixed finalization order, three WAVs and minutes.
**Milestone M1.**

## Depends on

02, 03, 04

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §3 (composition root), §6 (data flow, **stop order**, VRAM
  rule, pause), §8 (session folder, `session.json`, transcript precedence), §10 (conversation
  language)

## Scope

| File | Content |
|------|---------|
| `storage/session_store.py` | `SessionStore(output_dir)`: `create() -> SessionPaths`, atomic `write_meta`/`read_meta` (`session.json`, temp file + `os.replace`), `list_sessions()`, `load_transcript(id)` with the precedence rule, `paths(id)` |
| `session.py` | `RecordingSession`: `start()`, `pause()`, `resume()`, `stop()`; owns sources, writers, chunkers, worker; notifies a `SessionObserver` (`on_status`, `on_level`, `on_segment`, `on_language_detected`, `on_minutes_ready`, `on_error`); `stop()` follows architecture §6 exactly |
| `bootstrap.py` | registries `TRANSCRIBERS`, `LANGUAGE_MODELS`, `MIXERS`; `build_session(settings, *, language=None, mic_device=None, system_device=None) -> RecordingSession`; `build_minutes_generator(settings)` |
| `__main__.py` | argparse: `record [--language en|pt|es|auto] [--mic ID] [--system ID] [--list-devices]` and `minutes <session_dir>`; console observer prints segments and a one-line level meter (`hh:mm:ss  Me [####....]  Others [##......]`); `p` + Enter toggles pause; Ctrl+C stops |
| `.env.example` | add `GENERATE_MINUTES` |

## Design notes

- `RecordingSession` depends only on ports and factories passed in by `bootstrap.py`
  (Dependency Inversion); tests build it with fakes.
- `session.json` updated on every status change; `language` + `language_source`
  (`selected` / `detected`) written when known.
- Minutes failure (LLM down) must not lose anything: log, emit `on_error`, print how to retry with
  `python -m vozata minutes <dir>`.
- `minutes <dir>` uses `load_transcript` and the language stored in `session.json`.
- Echo, diarization, recovery and search hooks are added by later phases — keep `stop()` steps as
  small private methods so they can be extended without rewriting it.

## Acceptance criteria

- [ ] Session tests with fake sources/transcriber/LLM verify: start → segments reach observer and
      jsonl/md files; pause drops chunks and writes silence; stop order (writers finalized before
      mixer, `transcriber.close()` before minutes); minutes failure keeps status `done` with an
      error event.
- [ ] `session.json` content matches architecture §8 for a fake run.
- [ ] Manual E2E (record in the PR): `python -m vozata record --language pt`, play a video
      and speak for ~1 min → lines every ~`CHUNK_SECONDS`, no words cut mid-way; Ctrl+C → `mic.wav`,
      `system.wav`, `mixed.wav` equal length, `minutes.md` generated with Ollama running.
- [ ] Changing `CHUNK_SECONDS` and `MIX_MODE` in `.env` changes behaviour without code changes.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/test_session.py`, `tests/storage/test_session_store.py`, `tests/test_bootstrap.py`,
`tests/test_cli.py` (argparse + `minutes` command with fakes).

## Out of scope

HTTP API (06), UI (07+).

## Kickoff prompt

> Execute phase 05 of the roadmap (`docs/roadmap/phases/05-session-cli.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/05-session-cli`
- **Status:** in progress
- **Updated:** 2026-10-16 08:34
- **Next step:** write `tests/test_cli.py`, then replace `__main__.py` with the argparse CLI: `record [--language] [--mic] [--system] [--list-devices]` (console observer with segment lines + one-line level meter, `p`+Enter toggles pause, Ctrl+C stops) and `minutes <session_dir>`; add `cli.*` locale keys in en/pt-BR/es; keep `--version`.

### Steps

- [x] Start phase: status in progress, Progress section — `faabf68`
- [x] `GENERATE_MINUTES` config key — `e4b621d`
- [x] `storage/session_store.py` (`SessionStore`, `SessionPaths`) + tests — `2315176`
- [x] `session.py` (`RecordingSession`, `SessionObserver`) + tests; sources open with a timeout — `6d855a3`
- [x] `bootstrap.py` (`TRANSCRIBERS`, `LANGUAGE_MODELS`, `MIXERS`, `build_session`,
      `build_minutes_generator`) + tests
- [ ] `__main__.py` CLI (`record`, `minutes`, console observer + level meter) + locale keys + tests
- [ ] Manual E2E: `python -m vozata record --language pt`, then `minutes` with Ollama
- [ ] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- Phase 02 found that a WASAPI device open can hang for 30 s or forever (Intel Smart Sound mic
  driver). `RecordingSession.start()` opens each source on a worker thread with a timeout and fails
  with a localized error instead of blocking.

- `RecordingSession` is split by responsibility: `session.py` (state, stop order, mixer,
  transcriber release, minutes), `session_pipeline.py` (`CapturePipeline`: writers, chunkers,
  worker, sinks), `session_meta.py` (`SessionMeta`, thread-safe `session.json`) and
  `audio/opener.py` (`open_with_timeout`, 20 s default).
- `SessionObserver` is a port in `ports.py` (phase 06 implements it for the WebSocket).
- A session whose `auto` language never locked stores no `language` key; `minutes <dir>` then
  passes `auto` to the generator.
- Minutes are skipped (no error) when the transcript is empty or `GENERATE_MINUTES=false`.
