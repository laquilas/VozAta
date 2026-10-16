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

- [x] Session tests with fake sources/transcriber/LLM verify: start → segments reach observer and
      jsonl/md files; pause drops chunks and writes silence; stop order (writers finalized before
      mixer, `transcriber.close()` before minutes); minutes failure keeps status `done` with an
      error event.
- [x] `session.json` content matches architecture §8 for a fake run.
- [x] Manual E2E (record in the PR): `python -m vozata record --language pt`, play a video
      and speak for ~1 min → lines every ~`CHUNK_SECONDS`, no words cut mid-way; Ctrl+C → `mic.wav`,
      `system.wav`, `mixed.wav` equal length, `minutes.md` generated with Ollama running.
- [x] Changing `CHUNK_SECONDS` and `MIX_MODE` in `.env` changes behaviour without code changes.
- [x] Coverage ≥ 80 %.

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
- **Status:** ready for PR
- **Updated:** 2026-10-16 08:54
- **Next step:** open the PR (put the E2E results below in its description) and merge.

### Steps

- [x] Start phase: status in progress, Progress section — `faabf68`
- [x] `GENERATE_MINUTES` config key — `e4b621d`
- [x] `storage/session_store.py` (`SessionStore`, `SessionPaths`) + tests — `2315176`
- [x] `session.py` (`RecordingSession`, `SessionObserver`) + tests; sources open with a timeout — `6d855a3`
- [x] `bootstrap.py` (`TRANSCRIBERS`, `LANGUAGE_MODELS`, `MIXERS`, `build_session`,
      `build_minutes_generator`) + tests — `41010e8`
- [x] `__main__.py` CLI (`record`, `minutes`, console observer + level meter) + locale keys + tests — `21d40cb`
- [x] Manual E2E: `python -m vozata record --language pt`, then `minutes` with Ollama
- [x] Verify; tick acceptance criteria; set phase `done`

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
- **PortAudio thread (found in the E2E run)**: with one `PyAudio` per source created on the opener
  helper thread, the second device failed with `Unanticipated host error` (-9999). WASAPI binds
  PortAudio to the thread that initialized it, so `audio/portaudio.py` (`PortAudioThread`) owns a
  single `PyAudio` per session and runs every lookup/open/terminate on one long-lived thread.
- `WasapiSource` releases its native `soxr` resampler when capture ends; objects still alive at
  interpreter exit made nanobind print leak warnings after the CLI finished.
- **Manual E2E (2026-10-16)**: the real `python -m vozata record` ran end to end (`main()` driven
  by a script that stops it with a real `KeyboardInterrupt`, like Ctrl+C), recording the USB mic
  (JBL Quantum Stream) and the Realtek loopback while a ~58 s Portuguese meeting (Windows TTS,
  voice Maria) played on the speakers and a person spoke at the mic; `WHISPER_MODEL=large-v3`
  (the default turbo model is not fully downloaded on this machine).
  - `--language pt`: a line every ~5 s per channel, whole sentences, no words cut; `mic.wav`,
    `system.wav`, `mixed.wav` all 64.096 s; `minutes.md` written by Ollama `qwen2.5:7b`.
  - `--language auto`: Portuguese detected and stored (`language_source: detected`); WAVs 63.900 s.
  - `CHUNK_SECONDS=3 MIX_MODE=stereo GENERATE_MINUTES=false` from the environment: 2-channel
    `mixed.wav`, `CHUNK_SECONDS: 3.0` in `session.json`, no `minutes.md`.
  - `python -m vozata minutes <dir>` with `APP_LANGUAGE=pt-BR` rewrote the minutes in Portuguese.
  - The first run lost the opening "Bom dia a todos." on both channels: the speakers clipped the
    start of playback (the source file has it; later runs captured it).
  - The mic also transcribes what the speakers play (echo); phase 18 removes those duplicates.
