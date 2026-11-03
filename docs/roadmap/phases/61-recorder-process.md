# Phase 61 — Recorder process: record first, never lose audio

## Goal

The recording must start the moment the user presses Start, before the engine core is up (it
takes about a minute to answer `/health`), and it must survive an engine crash and an app crash
without losing a sample. Audio capture moves out of the engine into a small **recorder
process** (`vozata-recorder`) that starts in about a second and writes every sample to disk as
it comes. The engine attaches to the recording whenever it is up, replays what it missed through
the usual live pipeline, and processes the meeting after Stop. The temporary files are deleted
only after the engine has proved that every frame is in its store.

Requested by the user on 2026-11-03.

## Depends on

40, 41, 60

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (ports), §6 (start sequence, stop order), §8 (session
  folder, SQLite), §9 (keys)
- [phase 17](17-crash-recovery.md) (`repair_wav`, `find_interrupted`), [phase 26](26-capture-first.md),
  [phase 40](40-background-processing.md) (job steps), [phase 60](60-audio-import.md) (`import_pcm`)
- `engine/src/vozata/audio/{portaudio,capture,wav_writer,devices,clock}.py`,
  `storage/wav_repair.py`, `session.py`, `session_pipeline.py`, `api/session_manager.py`
- `ui/src/VozAta.Desktop/Services/EngineProcess.cs`, `ViewModels/RecorderPageViewModel.cs`,
  `ViewModels/MainViewModel.cs`

## Scope

**Recorder** (`engine/src/vozata/recorder/`, light imports only: numpy, soxr, pyaudiowpatch,
python-dotenv and the standard library; never `vozata.bootstrap`, `vozata.config`, `vozata.api`,
FastAPI, faster-whisper, PyAV or httpx)

| File | Content |
|------|---------|
| `__main__.py` | `python -m vozata.recorder` / `python -m vozata recorder` (dispatched before the heavy imports of `vozata/__main__.py`): `--port`, `--output-dir`; serves until `POST /shutdown` |
| `settings.py` | `RecorderSettings` read from `.env` with `dotenv_values` |
| `manifest.py` | `recording.json`: segments, gaps, pauses, options, heartbeat; atomic writes |
| `durable_track.py` | `DurableTrack`: the no-loss writer of one channel |
| `segment_reader.py` | `SegmentReader`: frames across segments, gaps as silence, file size as the truth |
| `recording.py` | `Recording`: devices, `WasapiSource` per channel, tracks, levels, pause, heartbeat, resume after a recorder crash |
| `http.py`, `app.py` | `ThreadingHTTPServer` with JSON routes and an SSE `/events` stream |
| `lock.py` | single instance: the port bind plus `live/recorder.lock` |

**Engine**

| File | Content |
|------|---------|
| `config.py`, `settings_fields.py`, `.env.example` | `RECORDER_ENABLED`, `RECORDER_PORT`, `RECORDER_FSYNC_SECONDS`, `RECORDER_MAX_SEGMENT_MB`, `RECORDER_BUFFER_WARN_SECONDS` |
| `audio/devices.py` | `resolve_devices` (moved from `bootstrap._devices`, shared with the recorder) |
| `storage/wav_repair.py` | public header helpers for the recorder |
| `ports.py` | `LiveRecordings`, `RecorderControl`; `SessionRepository.create(..., session_id=)`; `AudioStore.open_writer(..., append=)` |
| `audio/tail_source.py` | `TailingFileSource(AudioSource)`: tails a channel of a live recording into the unchanged `CapturePipeline` |
| `audio/recorder_clock.py` | `RecorderClock`: session time from the manifest's `started_at` |
| `session.py`, `session_live.py` | attach to a recorder recording (same id); reattach after an engine restart (append, segment ids continue) |
| `api/recorder_watcher.py`, `api/recorder_follower.py` | attach live recordings, follow pause / resume / stop, import stopped ones |
| `api/session_manager.py`, routes, schemas | `attach`, `reattach`, `recorder_id`, pause / resume / stop forwarded to the recorder, `capture_source` |
| `processing/ingest_check.py`, `session_job.py`, `bootstrap_processing.py` | `ingest` step: stored frames match the manifest (re-import what is missing), then delete `live/<id>/` |
| `storage/live_import.py` | `LiveRecordingImporter`: recordings the engine never saw are imported and queued at its next start |
| `storage/recovery.py` | a session still recorded by the recorder is never "interrupted" |
| `cli/record.py` | refuses while the recorder records (no double capture) |
| `bootstrap.py` | wiring; `RECORDER_ENABLED=false` keeps today's in-process capture |
| `packaging/recorder.spec`, `build.ps1`, `installer.iss` | `vozata-recorder.exe` in `{app}\recorder` |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client` | `IRecorderClient` / `RecorderClient`, `IRecorderEvents` (SSE, reconnect with backoff) |
| `Services/RecorderProcess.cs` | `IRecorderProcess`: start detached, poll `/health`, never kill |
| `appsettings.json`, `App.axaml.cs` | `Recorder` section and DI |
| `MainViewModel`, `RecorderPageViewModel` | recorder first at startup; Start / Pause / Stop / levels / elapsed through the recorder; engine events adopted by id |
| `ShellView.axaml` | a "Recorder" status dot next to the engine's |
| Resources | strings in en / pt-BR / es |

## Design notes

- **Files.** `OUTPUT_DIR/live/<YYYYMMDD_HHMMSS>/` holds `recording.json` and one continuous
  `mic.wav` and `system.wav`. A new segment (`mic-0002.wav`…) is opened **only on a failure**: a
  write error (disk, OneDrive lock), the size guard (`RECORDER_MAX_SEGMENT_MB`, below the WAV
  4 GB limit, no gap) or a recorder restart (the lost time is a `gap`).
- **No loss.** Samples go to an in-memory buffer that is never dropped; a writer thread appends
  them, and every `RECORDER_FSYNC_SECONDS` flushes, patches the header, fsyncs and records the
  frame count in the manifest. A stale header is repaired from the file size. Invariant per
  channel: segment frames + gap frames = total frames.
- **One id.** The recorder mints the id; the engine creates its store session with the same id,
  so the UI, the recorder and the engine name the meeting the same way.
- **Truth of pause and stop** is the manifest; the engine follows it.
- **Engine attach** replays from frame 0 (or from the transcript resume point after an engine
  restart) through the usual writers and chunkers: speech said before the engine came up is
  transcribed.
- **Deletion** of `live/<id>/` happens only in the `ingest` step, after the frame check.

## Acceptance criteria

- [ ] `vozata-recorder` answers `/health` within 2 s of launch; an import-budget test keeps
      heavy modules out.
- [ ] Start records at once while the engine is still starting; the sentences said before the
      engine attached appear in the transcript.
- [ ] Killing the engine during a recording: the recording continues; the restarted engine
      reattaches and the audio of the outage is stored and transcribed.
- [ ] Killing the app during a recording: the recorder keeps recording.
- [ ] Killing the recorder and starting it again: the recording continues in a new segment with
      a gap; the meeting has both parts.
- [ ] A forced write error opens a new segment and loses no sample.
- [ ] After Stop, `live/<id>/` is deleted only once the store matches the manifest.
- [ ] A recording stopped while the engine was down is imported and queued at the next start.
- [ ] `RECORDER_ENABLED=false` and the CLI `record` keep today's behavior.
- [ ] Contract docs updated; en / pt-BR / es parity; coverage ≥ 80 %.

## Tests

`tests/recorder/`, `tests/audio/test_tail_source.py`, `tests/api/test_attach.py`,
`tests/storage/test_live_import.py`, `tests/processing/test_ingest_check.py`;
UI `RecorderClientTests`, `RecorderEventsTests`, `RecorderProcessTests`,
`RecorderPageViewModelTests`, `MainViewModelTests`.

## Out of scope

Changing devices during a recording; recording on another PC; the gate on engine pages and the
reattach UX (phase 62); options edited during the recording (63); skipped minutes (64).

## Kickoff prompt

> Execute phase 61 of the roadmap (`docs/roadmap/phases/61-recorder-process.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/61-recorder-process`
- **Status:** in progress
- **Updated:** 2026-11-03 17:09
- **Next step:** write `recorder/manifest.py` and `recorder/segment_reader.py` with tests (`tests/recorder/`)

### Steps

- [x] Start the phase (README rows 61–64, phase files, Progress)
- [x] `wav_repair` header helpers public; `resolve_devices` moved
- [ ] `recorder/manifest.py` + `segment_reader.py`
- [ ] `recorder/durable_track.py` (no-loss writer)
- [ ] `recorder/recording.py`
- [ ] Recorder HTTP API (`http.py`, `app.py`, `lock.py`, `__main__.py`), config keys
- [ ] Engine ports, `TailingFileSource`, `RecorderClock`
- [ ] `create(session_id=)`, append writers, segment ids continue
- [ ] Attach / reattach, follower, recovery exclusions
- [ ] `ingest` step, `LiveRecordingImporter`, watcher, health
- [ ] CLI guard, bootstrap wiring, packaging
- [ ] UI client, SSE events, recorder process, fakes
- [ ] UI view models and views, strings
- [ ] Docs (architecture, api-contract), full suites, manual check, PR

### Decisions and notes

- Built in a git worktree outside OneDrive (`E:\VozAta-work\wt61`) because the user was
  recording with the main checkout's engine; tests run with `PYTHONPATH=<worktree>/engine/src`.
- The user wants extra segment files **only on failure** and no audio loss in any case
  (2026-11-03): one continuous WAV per channel normally.
