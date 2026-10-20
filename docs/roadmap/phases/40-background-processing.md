# Phase 40 — Background processing queue

## Goal

Back-to-back meetings. Today the recorder stays locked after Stop until the whole finalization
(last chunks, speaker identification, minutes, action items) is done, which takes minutes and
looks like a freeze. After this phase:

- **Stop frees the recorder at once**: a new meeting can start while the previous one is still
  being processed.
- Stopped meetings wait in a **processing queue** and are processed **one at a time, in the order
  they were stopped**, in the background.
- Each meeting being processed shows its **progress in %** (Meetings row, meeting page and a small
  shell indicator); when it is done the indicator **turns green and the % disappears**.
- A new meeting with live transcription **always has priority**: whatever GPU work the queue is
  doing is interrupted and redone later.

Requested by the user on 2026-10-20 ("finish one meeting and take part in the next one while the
previous one is processed").

## Depends on

17, 26, 37

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- `docs/roadmap/architecture.md` §5 (`AudioReader`), §6 (live pipeline, stop order, crash
  recovery), §7 (stitching), §16 (desktop shell)
- `docs/roadmap/api-contract.md` (`POST /sessions`, `POST /sessions/{id}/stop`, `/recover`,
  `/minutes`, `/ask`, `status` event)
- [phase 26](26-capture-first.md) (deferred model load), [phase 17](17-crash-recovery.md)
  (`interrupted`, repair, `recover`), [phase 33](33-folder-migration.md) (`MigrationJob` pause
  pattern), [phase 25](25-llm-vram-release.md) (VRAM ordering)

## Current state (facts, 2026-10-20)

- `SessionManager.stop()` (`api/session_manager.py`) starts a `finalize` thread and returns 202,
  but `_session` stays set until `RecordingSession.stop()` ends, so `start()` raises
  `SessionConflictError` (409 `session_already_active`) for the whole finalization. `recover()`
  takes the same slot ("VRAM rule: never next to a recording").
- `RecordingSession.stop()` (`session.py`): `_stop_capture()` (sources, chunker flush, PortAudio
  release, status `finalizing`) → `_drain()` (joins the transcription worker: waits for a model
  still loading, then transcribes every queued chunk) → `finalize_wavs()` → `_finish()` (mix,
  release transcriber, diarize, minutes, action items, index, `done`). `recover()` runs `_finish()`.
- Other model users outside the session: `MinutesJob` ("Regenerate minutes", own thread), Ask
  (phase 24), the Config connection / model tests.
- The live path: chunker (pure numpy, `feed(float32, at)`) → queue → `TranscriptionWorker` →
  `CarryOverStitcher` per channel → `EchoFilter` → sinks. Stored audio is readable through
  `AudioReader.frames(session_id, channel, start, count)` (int16) for both backends; nothing
  transcribes stored audio today.
- UI: `EngineProcess.StopIfStarted` kills the engine process tree when the app closes.
  `RecorderPageViewModel.CanStart()` is `State == Idle`, and the state returns to Idle only on a
  `status` event other than recording/paused/finalizing; `OnStatus` ignores `session_id`.
  `MeetingsPageViewModel` has one `Live` row; `MeetingRow.IsLive` includes `finalizing`.

## Scope

**Engine**

| File | Content |
|------|---------|
| `processing/queue.py` (new) | `ProcessingQueue`: FIFO of jobs, one daemon worker thread, one job at a time; progress state; `pending()` for the WebSocket connect snapshot |
| `processing/job.py` (new) | a job = named, weighted, **cancellable** steps: repair (only after a crash), transcribe, finalize WAVs, mix, diarize, minutes, action items, index, done; built from the existing `RecordingSession` methods |
| `processing/gpu_gate.py` (new) | `GpuGate` port + implementation shared by the queue, live sessions, Ask, Regenerate minutes and the Config tests (rules below) |
| `transcription/offline.py` (new) | `OfflineTranscription`: transcribes a session's stored audio **from a start time** to the end, through the same chunker → worker → stitcher → echo filter → transcript sinks used live; both channels fed in lockstep on one timeline; cancellable between blocks; reports audio seconds done / total |
| `session.py` | `stop_capture()` (fast: sources, PortAudio, the live worker finishes the chunk in hand and stops **without** draining its backlog, `capture_ended_at`, status `finalizing`); the rest moves into the job steps; `recover()` builds a job instead of running inline |
| `api/session_manager.py` | release the recording slot right after `stop_capture()` and enqueue the session; `start()` refuses only while another session records or pauses; `recover` enqueues; `busy` keeps meaning "recording or processing" for the migration job |
| `api/minutes_job.py` | "Regenerate minutes" becomes a queue job (minutes + action items + index steps) |
| `qa/`, `connection_checks.py` | acquire the gate (below) |
| `api/schemas.py`, routes | `processing` on summaries and detail; contract changes below |
| `bootstrap.py` | build the queue and the gate in the composition root; on start, re-enqueue unfinished meetings (below) |
| `session_meta.py` | `capture_ended_at` |
| `locales/*.toml` | step names, messages |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client` | `ProcessingEvent` (parser + DTO); `processing` on `SessionSummary` / detail |
| `RecorderPageViewModel` | back to Idle as soon as the stop request is accepted; `OnStatus` only follows the session it recorded |
| `MeetingsPageViewModel`, `MeetingRows.cs`, `MeetingsPage.axaml` | per-row state: "Queued (2)" / "Processing 42 %" / "Paused" badge; green check when done (below); `IsLive` no longer includes `finalizing` |
| `SessionPageViewModel`, `SessionPage.axaml` | the same indicator in the header; minutes / speakers tabs say "being processed" until their step ends |
| `ShellView.axaml` + `ProcessingIndicatorViewModel` | sidebar indicator under the recording one: "Processing 1 meeting · 42 %" (+ "2 queued") |
| `MainViewModel` | route `processing` events; on close with work pending, tell the user it resumes next time |
| Resources | strings in en / pt-BR / es |

## Design notes

### Statuses, event and percent

- No new status value. A stopped meeting stays `finalizing` from Stop until `done`; the new
  `processing` object says where it is: `{state: "queued" | "running" | "paused", percent: 0–100,
  step: "repair" | "transcribe" | "diarize" | "minutes" | "action_items" | "index", position: n}`
  (`position` only when queued, 1 = next). Absent when the meeting is not in the queue.
- New event **`processing`** (`session_id` in the envelope): on every state or step change and at
  most once per second while the percent moves; on WebSocket connect, one per pending meeting. The
  last one has `state: "done"` (or `"failed"`) right before the `status: done` event.
- Percent: step-weighted and **never goes down on screen**, even when an interrupted step is redone
  (the redo shows the same percent until it passes the old value). Weights are the builder's call;
  the transcribe step is weighted by audio seconds left to transcribe (small after a live meeting,
  most of the job for an audio-only one, phase 41).

### What Stop does (resolves the drain problem)

- Stop does **not** drain the live backlog. The live worker finishes the chunk in hand and stops,
  so its model is freed at once and never sits next to the queue's work.
- The job's **transcribe** step transcribes from stored audio whatever the live transcript did not
  cover: from the end of the last committed segment of each channel (minus the stitcher's overlap,
  so nothing is cut) to the end of the recording. After a normal live meeting this is a few
  seconds; when the model was still loading at Stop (e.g. downloading), it is the whole meeting.
- The same step serves phase 41 (audio-only meetings start from 0) and crash recovery (below).

### GPU gate (resolves interruptions and other model users)

- **Who uses the local GPU** is computed from the settings, per consumer: speech (faster-whisper
  on CUDA; not the external STT of phase 12 or CPU), speakers (pyannote on CUDA), LLM (Ollama with a
  local URL; phase 43 adds the remote case). On a machine without CUDA nothing is gated.
- **Priority**: live recording > Ask > Config tests > queue.
- **The user's rule**: when a live recording that uses the local GPU starts (or Ask / a Config
  test runs), the queue's **running GPU step is cancelled** within ≤ 5 s and redone from its start
  later (the transcribe step resumes from where it stopped). The job shows `paused` and resumes
  when the higher-priority user ends. Capture and the new meeting's live transcript start
  immediately; they never wait for the queue.
- Cancelling: the LLM step closes its HTTP request (Ollama stops generating); transcription
  stops between blocks; the diarizer is aborted through pyannote's progress `hook` raising a
  cancellation, or run in a child process that is terminated (builder's call). Partial outputs of
  a cancelled step are discarded.
- Steps without GPU (repair, finalize WAVs, mix, index) are never cancelled.
- A recording without live transcription (phase 41) or whose speech runs elsewhere does not touch
  the queue.
- "Regenerate minutes" is a queue job (FIFO behind the others). Ask and Config tests wait for the
  cancelled step to release the GPU (≤ 5 s), then run.

### Closing the app and crashes

- Closing the app with a non-empty queue shows "N meetings are still being processed; it resumes
  the next time VozAta opens" and closes without waiting (the engine is killed).
- On engine start, a `finalizing` session **with** `capture_ended_at` is re-enqueued (oldest first):
  its job starts with the phase 17 **repair** step (WAV repair / committed chunks), then transcribe
  (picks up from the last committed segment), then the rest. One **without** it is a crash during
  capture: `interrupted` as today; "Recover" enqueues the same job.

### Other rules

- **Failures**: a failing step reports its `error` event as today (`diarization_failed`,
  `minutes_failed`, …); the job continues with the next step and the meeting ends `done`. The
  queue never stops on one meeting's failure.
- **Delete / rename while queued**: rename is allowed. `DELETE /sessions/{id}` and
  `DELETE /sessions/{id}/audio` answer 409 `session_still_active` while the meeting is queued or
  running.
- **Green when done**: when a meeting's processing ends, its row and page indicator turn into a
  green check without %; it stays until the meeting is opened or the app restarts (an "unseen
  result" marker kept in the UI only).
- **Contract changes**: `POST /sessions` is allowed while meetings are processing;
  `/recover` and `/minutes` answer 202 and enqueue (no more 409 `session_already_active` for
  processing); `capture_ended_at` in `session.json` / the sessions table.

## Acceptance criteria

- [ ] After Stop, Start is enabled within 2 s; the next meeting records and shows its live
      transcript at once, while the first is still being processed.
- [ ] Three meetings stopped one after the other are processed one at a time, in stop order; the
      queued ones show "Queued" with position and the running one "Processing N %".
- [ ] The percent never goes down; at the end the indicator turns green and the % disappears.
- [ ] Starting a live recording while a queued meeting is writing its minutes (local Ollama)
      cancels that step within 5 s ("Paused"); after Stop it is redone and the meeting finishes.
- [ ] A meeting stopped while its speech model was still loading gets its full transcript from the
      transcribe step.
- [ ] Closing the app with a non-empty queue warns and closes; the next start repairs, resumes and
      finishes those meetings with complete transcripts.
- [ ] A failing step (e.g. Ollama down) does not block the meetings behind it.
- [ ] Contract docs updated (`processing` event and field, start / recover / minutes rules,
      `capture_ended_at`, gate in architecture §6).

## Tests

Engine (fakes only): queue order and single worker; gate priorities and cancellation of each
cancellable step kind; redo after cancel; percent monotonic; offline transcription from an
offset (lockstep channels, overlap, echo filter, progress, cancel between blocks); stop without
drain; re-enqueue on start with / without `capture_ended_at` (repair first); failure isolation;
start allowed while processing and refused while recording; delete refused while queued;
Regenerate minutes as a job; connect snapshot. UI: recorder Idle on stop accepted and ignoring
other sessions' `status`; row badge states (queued, running %, paused, green); indicator text;
close-with-pending message; locale parity.

## Out of scope

- The record-only option (phase 41).
- Model download progress (phase 42).
- Remote Ollama rules (phase 43).
- Reordering or cancelling queued meetings by the user.

## Progress

- **Branch:** `feature/40-background-processing`
- **Status:** in progress
- **Updated:** 2026-10-20 18:30
- **Next step:** Task 7 of `plans/40-background-processing.md` (Restart and recovery through the
  queue).

### Steps

- [x] Phase files 40-43, roadmap rows and the implementation plan
- [x] Cancel token and GPU gate
- [x] Cancellable LLM and diarizer (fix round 1: release after cancel, cancel before spawn)
- [x] Session finisher steps (0f2a1ad)
- [x] Offline transcription of the rest of a meeting (17ceaad, 09a2b95; fix round 2: this commit)
- [x] Processing job and queue (04afa22; fix round 1: this commit)
- [x] Stop frees the recorder (c7756b8, dab272b; fix round 1: this commit)
- [ ] Restart and recovery through the queue
- [ ] API, events and other model users
- [ ] UI client and recorder
- [ ] Meetings and meeting page indicators
- [ ] Shell indicator and close warning
- [ ] Full suites, manual check

### Decisions and notes

- Designed with the user on 2026-10-20: a new live recording interrupts the queue's running GPU step
  (redone later); after Stop the rest of the transcript comes from the stored audio; processing
  resumes after the app is closed. The implementation plan is `plans/40-background-processing.md`.
- Offline transcription (`transcription/offline.py`) seeds each channel's rolling context with its
  written text and the echo filter with the written system segments, so the appended rows match
  what the live pipeline would have produced; echo holds run on audio time. Fix round 1: each
  channel resumes after the voiced tail (≤ 0.3 s) the live stitcher cut away after its last
  segment, the stored system segments reach the echo filter as the timeline advances (its 30 s
  memory follows the audio fed), and the lockstep feed lives in `transcription/offline_feed.py`.
  Fix round 2: the tail is skipped only when it ends in silence within 0.3 s; still voiced at the
  cap (likely the next word) it is kept, since a repeated fragment is better than a lost word
  start.
- Stop (Task 6): `stop_capture()` abandons the live pipeline, which closes its sinks, transcriber
  and WAVs on its own thread and then sets `closed`; the job's `before` waits for it. The job
  (`processing/session_job.py`) is shared by `serve` (`bootstrap.build_processing_job`, providers
  built from `session.json` per step attempt) and the CLI (`RecordingSession.stop()` runs it
  inline with the session's own components). The live GPU lease is taken on the model-load
  thread, not in `start()`, so `POST /sessions` never waits for the queue's step to stop. After
  capture ends, `SessionMeta` merges its writes into the stored `session.json` and the heartbeat
  stops (it would race the job's writes). The transcribe weight is estimated from the raw
  transcript and the recorded length (the WAVs are not final yet at Stop); `finalize` is done by
  the abandoned pipeline, so the job has a single `mix` step.
  Fix round 1: `stop_capture()` logs a failing part and always abandons the pipeline (the live
  model and GPU lease are always released); a new recording's model load waits for the previous
  session's `closed` (`LiveModelTurn`); the transcribe step leases the kept Whisper on the GPU
  (`WHISPER_KEEP_LOADED`); the CLI still prints the lines transcribed after Stop; `before` warns
  every 5 min while it waits; the job's composition moved to `bootstrap_processing.py`.
