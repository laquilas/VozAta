# Phase 26 — Capture first, load later

## Goal

Pressing Start records **immediately**. Today `RecordingSession.start()` blocks ~20–25 s while
Whisper loads and nothing said meanwhile is captured (seen in the phase 07 manual check). Open the
devices first, queue audio while the model loads, then transcribe the backlog. Optionally keep the
model loaded between sessions. Origin: [optimizations.md](../optimizations.md) O2.

## Depends on

06, 07

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [optimizations.md](../optimizations.md) — O2
- [architecture.md](../architecture.md) §6 (start sequence, stop order, VRAM rule)
- [api-contract.md](../api-contract.md) — `model_loading` event

## Scope

| Item | Content |
|------|---------|
| `session.py`, `session_pipeline.py` | start order: folder → writers → sources (status `recording`) → transcriber loaded on the worker thread; chunks wait in the queue; the backlog warning is silenced until the model is ready; a failed load emits `error` and keeps recording WAVs (transcribe later is out of scope) |
| `api/session_manager.py` | publish `model_loading` `{loading: true|false}` |
| `config.py`, `.env.example` | `WHISPER_KEEP_LOADED` (`false`): in `serve`, keep the transcriber between sessions; still released before diarization/minutes (VRAM rule) and reloaded on the next start |
| UI `MainViewModel` / `MainWindow` | while `model_loading` is true show "Loading the speech model — already recording" next to the elapsed time; Start no longer waits in `Starting` |
| Locales / `.resx` | new strings in en, pt-BR, es |

## Design notes

- Start latency target: status `recording` within 2 s of the request (device open time only).
- The stop order (§6) is unchanged: draining the queue may take longer when the model was still
  loading at stop; finalization waits for it.

## Acceptance criteria

- [ ] Session tests: `recording` before the transcriber factory returns; every chunk queued during
      the load is transcribed; a failing load reports `error` and still produces WAVs.
- [ ] API test: `model_loading` true then false, in order, around the load.
- [ ] ViewModel test: loading indicator shown and hidden; Start → Recording without waiting.
- [ ] Manual: speak right after pressing Start → the first words appear in the transcript.
- [ ] Coverage ≥ 80 % (engine and UI).

## Tests

`tests/test_session.py`, `tests/api/test_session_manager.py`, `MainViewModelTests.cs`.

## Out of scope

Transcribing a session whose model never loaded (backlog: "transcribe later" from the WAVs).

## Kickoff prompt

> Execute phase 26 of the roadmap (`docs/roadmap/phases/26-capture-first.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/26-capture-first`
- **Status:** in progress
- **Updated:** 2026-10-16 20:20
- **Next step:** `WHISPER_KEEP_LOADED` in `serve`: a shared transcriber (`transcription/shared.py`) used by `build_api_container`'s sessions, released before session minutes and before `POST /sessions/{id}/minutes` (`MinutesJob`), closed when the API stops

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Config: `WHISPER_KEEP_LOADED` — `bf6a1c8`
- [x] Capture first: sources open and `recording` is reported before the transcriber loads; the
      worker loads it on its thread (`SessionObserver.on_model_loading`), queued chunks are
      transcribed afterwards; a failed load reports `model_failed` and keeps recording WAVs; CLI
      messages — this commit
- [x] API: `model_loading` `{loading}` event — same commit (the observer method is one change)
- [ ] `WHISPER_KEEP_LOADED` in `serve`: shared transcriber, released before minutes (session and
      `POST /sessions/{id}/minutes`)
- [ ] UI: `ModelLoadingEvent`, loading indicator next to the elapsed time; en / pt-BR / es strings
- [ ] Manual: speak right after Start → first words in the transcript; acceptance criteria

### Decisions and notes

- New observer method `SessionObserver.on_model_loading(loading: bool)` (architecture §5): the
  session already reports everything through the observer, so the API event and the CLI message
  come from it without new plumbing.
- The transcriber is loaded by `TranscriptionWorker` on its own thread after the sources are open
  (spec order); `CapturePipeline` takes the transcriber **factory** instead of an instance and
  builds the stitchers once it is loaded. The backlog warning cannot fire before the load because
  the worker does not consume chunks until then.
- Failed load: `error` `model_failed`, chunks are dropped, WAVs keep recording; the session stops
  normally (transcribing later from the WAVs is out of scope).
