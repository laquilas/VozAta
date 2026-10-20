# Phase 40 — Background Processing Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop frees the recorder at once; stopped meetings are finished one at a time by a background queue that reports progress, and a live recording always pre-empts the queue's GPU work.

**Architecture:** `RecordingSession.stop_capture()` ends capture without draining the live backlog; the session's slot is released and a `ProcessingJob` (repair → transcribe-the-rest-from-stored-audio → finalize/mix → diarize → minutes → action items → index → done) is put on a single-worker `ProcessingQueue`. A shared `GpuGate` lets live recordings, Ask and Config tests cancel the queue's running GPU step, which is redone later. The UI follows a new `processing` event.

**Tech Stack:** Python 3.13 (FastAPI, httpx, numpy, pytest), C# .NET 10 / Avalonia 12 (CommunityToolkit.Mvvm, xUnit).

**Spec:** `docs/roadmap/phases/40-background-processing.md` (read it first; this plan argues from it).

## Global Constraints

- English only in code, comments, docs, commits, branch names and log messages.
- Every user-facing string comes from locales: engine `src/vozata/locales/{en,pt-BR,es}.toml`, UI `Resources/Strings{,.pt-BR,.es}.resx`; every new key in all three (parity tests enforce it).
- Ports are `Protocol`s in `ports.py`; concrete classes are wired only in `bootstrap.py` (engine) and `App.axaml.cs` (UI).
- Unit tests never touch audio hardware, GPU, network or real LLMs; use `tests/fakes.py` fakes and `httpx.MockTransport`.
- Modules stay near ~200 lines; one responsibility per module.
- Diff coverage ≥ 80 %; every new class, branch and bug fix has tests.
- LF line endings; never commit CRLF.
- Branch `feature/40-background-processing`; one logical change per commit; every commit also updates the phase file's **Progress** (tick the step, set *Next step*) and is pushed.
- Commit messages: Conventional Commits, English, **no `Co-Authored-By` trailer**.
- Engine commands from `engine/`: tests `../.venv/Scripts/python -m pytest -q`, lint `../.venv/Scripts/ruff check src tests`, format `../.venv/Scripts/ruff format src tests`. UI commands from `ui/`: `dotnet test`, `dotnet format --verify-no-changes`.
- Shared contract changes go into `docs/roadmap/api-contract.md` / `architecture.md` in the task that makes them.

## Review Focus

1. **Stop while the speech model is still loading or downloading**: Stop must return and free the slot without waiting for the load; the queue's transcribe step must not start before the abandoned worker has closed the transcript sink (pinned in Task 6).
2. **Start pressed while the previous stop is still in `stop_capture()`**: `POST /sessions` answers 409 `session_already_active` until the slot is released, then succeeds; never two captures (pinned in Task 6).
3. **Restart with a queued meeting whose raw transcript already has segments**: the resumed transcription continues segment ids (`mic-000013` after `mic-000012`), never rewrites or duplicates committed segments (pinned in Task 4).
4. **Cancel arriving while a step is finishing**: a step that completed is never run again and its event (`minutes_ready`, `speakers_relabeled`) is sent once (pinned in Task 5).
5. **Delete or delete-audio of a queued meeting**: refused with 409 `session_still_active` until the job ends; allowed afterwards (pinned in Task 8).

---

### Task 0: Branch, phase start and plan

**Files:**
- Modify: `docs/roadmap/README.md` (row 40 → `in progress (\`feature/40-background-processing\`)`)
- Modify: `docs/roadmap/phases/40-background-processing.md` (append **Progress**, template in `docs/roadmap/README.md`)
- Add: `docs/roadmap/phases/41-record-only.md`, `42-download-progress.md`, `43-remote-ollama.md`, `plans/40-background-processing.md` (already written, uncommitted on `main`)

- [ ] **Step 1:** `git switch -c feature/40-background-processing` from an up-to-date `main` (the uncommitted phase files move with the working tree).
- [ ] **Step 2:** Progress steps = Tasks 1–12 of this plan; *Next step* = Task 1.
- [ ] **Step 3:** Commit `docs(roadmap): plan phases 40-43 and start phase 40`; push with `-u`.

### Task 1: Cancellation token and GPU gate

**Files:**
- Create: `engine/src/vozata/processing/__init__.py`, `engine/src/vozata/processing/cancel.py`, `engine/src/vozata/processing/gpu_gate.py`
- Modify: `engine/src/vozata/ports.py` (add `Cancellable`)
- Test: `engine/tests/processing/test_cancel.py`, `engine/tests/processing/test_gpu_gate.py`

**Interfaces:**
- Produces:
  - `ports.Cancellable(Protocol)`: `def cancel(self) -> None` ("stop the current call from another thread; the call raises").
  - `cancel.StepCancelled(Exception)`; `cancel.CancelToken` with `cancelled: bool` (property), `cancel() -> None` (idempotent, runs registered callbacks once, outside its lock), `on_cancel(callback: Callable[[], None]) -> Callable[[], None]` (returns an unregister function; a callback registered after `cancel()` runs at once), `raise_if_cancelled() -> None`.
  - `gpu_gate.GpuUser(StrEnum)`: `LIVE`, `ASK`, `CHECK`, `QUEUE`.
  - `gpu_gate.GpuUsage` frozen dataclass `speech: bool, speakers: bool, llm: bool`; `gpu_usage(settings: Settings, cuda: bool) -> GpuUsage` — speech = `stt_provider == "faster_whisper"` and device not `cpu` and `cuda`; speakers = diarization or live diarization enabled and `diarization_device` not `cpu` and `cuda`; llm = `llm_provider == "ollama"` (phase 43 adds the URL check) and `cuda`.
  - `gpu_gate.GpuGate(cancel_timeout: float = 5.0)`:
    - `priority(user: GpuUser) -> AbstractContextManager[None]` — enter: cancels the token of a running queue step, waits up to `cancel_timeout` for it to leave (logs a warning if it does not, then proceeds); several priority users may hold at once.
    - `queue_step(token: CancelToken, on_wait: Callable[[], None]) -> AbstractContextManager[None]` — enter: blocks while any priority user holds (calls `on_wait` once if it has to wait); exit releases. Raises `StepCancelled` on enter if `token` is already cancelled.
    - `priority_held: bool` property.

- [ ] **Step 1: Write the failing tests**

```python
def test_cancel_runs_callbacks_once_and_late_callbacks_immediately(): ...
    # token.on_cancel(a); token.cancel(); token.cancel() -> a called once; token.on_cancel(b) -> b called at once
def test_unregistered_callback_is_not_called(): ...
def test_priority_cancels_running_queue_step_and_waits_for_it():
    # queue thread holds queue_step(token); main enters priority(LIVE) -> token.cancelled is True,
    # priority enter returns only after the queue thread exits its step
def test_queue_step_waits_while_priority_held_and_calls_on_wait_once(): ...
def test_two_priority_users_hold_together(): ...
def test_priority_proceeds_after_cancel_timeout_when_step_ignores_cancel(caplog): ...  # cancel_timeout=0.05
def test_gpu_usage_table():  # parametrize: (provider, device, cuda) -> speech flag; same for speakers and llm
    assert gpu_usage(settings(stt_provider="faster_whisper", whisper_device="auto"), cuda=False).speech is False
```

- [ ] **Step 2:** Run `../.venv/Scripts/python -m pytest tests/processing -q` → FAIL (module missing).
- [ ] **Step 3:** Implement with one `threading.Condition`; `priority` counts holders, `queue_step` records the running token.
- [ ] **Step 4:** Run the tests → PASS; ruff clean.
- [ ] **Step 5:** Commit `feat(engine): add a cancel token and a GPU gate for background work` (+ Progress).

### Task 2: Cancellable LLM and diarizer

**Files:**
- Modify: `engine/src/vozata/llm/ollama.py`, `engine/src/vozata/diarization/subprocess_diarizer.py`, `engine/src/vozata/minutes/generator.py`, `engine/src/vozata/minutes/action_items.py`
- Test: `engine/tests/llm/test_ollama.py`, `engine/tests/diarization/test_subprocess_diarizer.py`, `engine/tests/minutes/test_generator.py`, `engine/tests/minutes/test_action_items.py`

**Interfaces:**
- Consumes: `ports.Cancellable` (Task 1).
- Produces: `OllamaLanguageModel.cancel()` (closes the HTTP client; the call in flight and later calls raise `LanguageModelError`); `SubprocessDiarizer.cancel()` (switches from `subprocess.run` to `Popen` + `communicate`; `cancel()` terminates the running child, `diarize` then raises `DiarizationError("cancelled")`; constructor takes `popen: Popen = subprocess.Popen` instead of `run`); `MinutesGenerator.cancel()` and `ActionItemExtractor.cancel()` forward to their model when it is `Cancellable`, else no-op.

- [ ] **Step 1: Write the failing tests**

```python
def test_cancel_during_generate_raises_language_model_error():
    # MockTransport handler blocks on an Event; another thread calls model.cancel(); generate raises LanguageModelError
def test_cancel_terminates_child_and_diarize_raises(): ...  # fake Popen records terminate()
def test_generator_cancel_forwards_to_cancellable_model(): ...  # FakeLanguageModel gains cancel() counting calls
def test_generator_cancel_without_cancellable_model_is_noop(): ...
```

- [ ] **Step 2:** Run the four files → FAIL.
- [ ] **Step 3:** Implement; add `cancel()` to `FakeLanguageModel` / `FakeDiarizer` in `tests/fakes.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(engine): let a running LLM call or diarizer child be cancelled`.

### Task 3: Session finisher steps out of `RecordingSession`

Pure refactor that later tasks build on: the post-capture steps become a class that works from stored data alone, so the live stop and recovery share it.

**Files:**
- Create: `engine/src/vozata/session_finisher.py`
- Modify: `engine/src/vozata/session.py` (`_finish()` delegates to the finisher; behavior unchanged), `engine/src/vozata/bootstrap.py` (`build_recovery_session` → also `build_finisher(settings, store, audio, observer, session_id) -> SessionFinisher` from stored meta, reusing its component logic)
- Test: `engine/tests/test_session_finisher.py` (move the step tests from `test_session.py` / `test_session_diarization.py` / `test_session_action_items.py` / `test_session_search.py` that only exercise steps 3–7)

**Interfaces:**
- Produces: `SessionFinisher(settings, store: SessionRepository, audio: SessionAudio, components: SessionComponents, observer: SessionObserver, session_id: str, language: LanguageLock, title: Callable[[], str | None])` with methods, each catching and reporting its own error exactly as today:
  - `mix() -> None`
  - `identify_speakers(token: CancelToken) -> None` — registers `token.on_cancel(diarizer.cancel)` while diarizing; when cancelled raises `StepCancelled` (no `diarization_failed` event, nothing written).
  - `write_minutes(token: CancelToken) -> None` — same pattern with `MinutesGenerator.cancel`; `minutes_ready` only after a write.
  - `extract_action_items(token: CancelToken) -> None`
  - `index() -> None`
  - `ended(at: datetime) -> None` (meta `ended_at`, status `done`).
- `RecordingSession._finish()` calls these in today's order with a never-cancelled token.

- [ ] **Step 1:** Move the tests; add `test_identify_speakers_cancelled_raises_and_writes_nothing` and `test_write_minutes_cancelled_sends_no_minutes_ready` (fake diarizer / model whose call blocks until `cancel()`).
- [ ] **Step 2:** Run → the two new tests FAIL, moved ones fail on import.
- [ ] **Step 3:** Extract the class; `session.py` shrinks accordingly.
- [ ] **Step 4:** Full engine suite → PASS.
- [ ] **Step 5:** Commit `refactor(engine): move the stop steps into a session finisher`.

### Task 4: Transcribe the rest of a meeting from stored audio

**Files:**
- Create: `engine/src/vozata/transcription/offline.py`, `engine/src/vozata/transcription/resume.py`
- Modify: `engine/src/vozata/transcription/stitcher.py` (`SegmentIds(start: Mapping[Channel, int] | None = None)`)
- Test: `engine/tests/transcription/test_offline.py`, `engine/tests/transcription/test_resume.py`, `engine/tests/storage/repository_contract.py` (append contract)

**Interfaces:**
- Produces:
  - `resume.ResumePoint` frozen dataclass `start: float, next_index: int`; `resume.resume_points(segments: Sequence[TranscriptSegment], channels: Iterable[Channel]) -> dict[Channel, ResumePoint]` — `start` = max `end` of that channel's raw segments (0.0 when none), `next_index` = highest `<channel>-NNNNNN` number + 1 (1 when none).
  - `OfflineTranscription(settings: Settings, store: SessionRepository, audio: AudioReader, transcriber_factory: Callable[[], Transcriber], labeler: SpeakerLabeler, language: LanguageLock, hints: str | None, chunker_factory: ChunkerFactory | None, block_seconds: float = 10.0)`:
    - `remaining_seconds(session_id: str) -> float` (sum over channels of track length − resume start; for job weights).
    - `run(session_id: str, token: CancelToken, on_progress: Callable[[float], None]) -> None` — loads the transcriber, reads both channels in `block_seconds` blocks from their resume points **in lockstep on one timeline** (int16 → float32 / 32768), feeds the session's chunkers, stitches synchronously on this thread (no `TranscriptionWorker`), passes segments through `EchoFilter` (its `clock` = the audio time fed so far, so holds follow audio time) into `store.open_transcript(...)` (append). Checks `token` between blocks: when cancelled it closes the sink **without** flushing the stitchers, closes the transcriber and raises `StepCancelled`. At the end it flushes stitchers, closes the sink and the transcriber. `on_progress` gets 0..1 = audio seconds fed / `remaining_seconds` at start.

- [ ] **Step 1: Write the failing tests**

```python
def test_resume_points_from_existing_segments():
    assert resume_points([seg("mic-000012", 0, 40.5), seg("system-000003", 2, 30)], CHANNELS) == {
        Channel.MIC: ResumePoint(40.5, 13), Channel.SYSTEM: ResumePoint(30.0, 4)}
def test_resume_points_without_segments_start_at_zero(): ...
def test_offline_continues_ids_and_appends_after_existing_segments(): ...  # Review Focus 3
    # store has mic-000012 ending at 40.5; run -> new ids start at mic-000013, starts >= 40.5, old rows untouched
def test_offline_feeds_channels_in_lockstep(): ...  # FakeTranscriber records call order: mic/system blocks alternate by time
def test_offline_echo_filter_drops_mic_copy_of_system_speech(): ...
def test_offline_progress_reaches_one_and_is_monotonic(): ...
def test_offline_cancel_between_blocks_raises_and_keeps_committed_segments(): ...
def test_offline_closes_transcriber_on_success_and_on_cancel(): ...
# repository_contract.py:
def test_open_transcript_on_session_with_segments_appends(repo): ...  # both backends
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Reuse `CarryOverStitcher`, `RollingContext`, the chunker factory and `_echo_filter` logic (move `_echo_filter` from `session_pipeline.py` to `transcription/echo.py` if needed to avoid importing a private name).
- [ ] **Step 4:** Run → PASS; full suite green.
- [ ] **Step 5:** Commit `feat(engine): transcribe the rest of a meeting from its stored audio`.

### Task 5: Processing job and queue

**Files:**
- Create: `engine/src/vozata/processing/job.py`, `engine/src/vozata/processing/queue.py`
- Test: `engine/tests/processing/test_job.py`, `engine/tests/processing/test_queue.py`

**Interfaces:**
- Consumes: `CancelToken`, `StepCancelled`, `GpuGate` (Task 1).
- Produces:
  - `job.StepKind(StrEnum)`: `REPAIR="repair"`, `TRANSCRIBE="transcribe"`, `FINALIZE="finalize"`, `MIX="mix"`, `DIARIZE="diarize"`, `MINUTES="minutes"`, `ACTION_ITEMS="action_items"`, `INDEX="index"`. Only `repair`, `transcribe`, `diarize`, `minutes`, `action_items`, `index` are shown in events; `finalize` / `mix` report as the step that follows.
  - `job.Step` frozen dataclass: `kind: StepKind`, `weight: float`, `gpu: bool`, `run: Callable[[CancelToken, Callable[[float], None]], None]`.
  - `job.ProcessingJob` frozen dataclass: `session_id: str`, `steps: tuple[Step, ...]`, `before: Callable[[], None] = lambda: None` (Task 6 uses it to wait for the live sink), `on_finished: Callable[[], None]` (meta ended + status done).
  - `queue.ProcessingState` frozen dataclass: `session_id`, `state: Literal["queued", "running", "paused", "done", "failed"]`, `percent: int`, `step: StepKind | None`, `position: int | None`; `to_payload() -> dict` (omits `position` unless queued, `step` as its shown value).
  - `queue.ProcessingQueue(gate: GpuGate, publish: Callable[[ProcessingState], None], clock: Callable[[], float] = time.monotonic, progress_interval: float = 1.0)`: `start()` (daemon thread `processing`), `enqueue(job) -> None` (publishes `queued` for it and new positions for the others), `state(session_id) -> ProcessingState | None`, `pending() -> list[ProcessingState]` (running first, then queued in order), `contains(session_id) -> bool`, `wait_idle(timeout: float | None = None) -> bool`, `stop()` (tests).
- Rules (from the spec): FIFO, one job at a time; a `gpu` step runs inside `gate.queue_step(token, on_wait=<publish paused>)`; `StepCancelled` → publish `paused`, retry the same step with a fresh token after the gate frees; any other exception is logged and the job continues with the next step; percent = completed weights + fraction × current weight, renormalized to 100, published at most once per `progress_interval` and **never lower than the last published value**; after the last step: publish the `done` state, then `on_finished()` (which sends `status: done`), then the job is removed; a raising `on_finished` is logged and publishes `failed`.

- [ ] **Step 1: Write the failing tests**

```python
def test_jobs_run_one_at_a_time_in_enqueue_order(): ...
def test_queued_states_carry_positions_and_update_when_one_starts(): ...
def test_percent_is_monotonic_and_reaches_100_with_done_last(): ...
def test_cancelled_gpu_step_is_paused_then_redone_and_done_once(): ...  # Review Focus 4
    # step raises StepCancelled the first time only; its side effect counter == 1 after a successful redo;
    # a step that completed before the cancel is not run again
def test_failing_step_does_not_stop_the_job_or_the_queue(): ...
def test_non_gpu_steps_ignore_the_gate(): ...
def test_progress_is_throttled_to_the_interval(): ...  # fake clock
def test_pending_lists_running_then_queued(): ...
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement (job.py: data only; queue.py: worker loop, state, publishing).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(engine): add the background processing queue`.

### Task 6: Stop frees the recorder

**Files:**
- Modify: `engine/src/vozata/transcription/worker.py` (`abandon()`), `engine/src/vozata/session_pipeline.py` (`abandon(on_closed)`), `engine/src/vozata/session.py` (`stop_capture()`), `engine/src/vozata/session_meta.py` (`capture_ended_at`), `engine/src/vozata/api/session_manager.py`, `engine/src/vozata/bootstrap.py` (`build_processing_job`, queue + gate wiring; live sessions take `gate.priority(GpuUser.LIVE)` when `gpu_usage().speech or .speakers`), `docs/roadmap/architecture.md` §6 (new stop order, queue, gate)
- Test: `engine/tests/transcription/test_worker.py`, `engine/tests/test_session.py`, `engine/tests/api/test_session_manager.py`, `engine/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces:
  - `TranscriptionWorker.abandon(on_exit: Callable[[], None]) -> None` — returns at once; the thread finishes the chunk in hand (or its model load), skips the backlog and stitcher flush, then calls `on_exit` on its own thread. Without a started thread `on_exit` runs at once.
  - `CapturePipeline.abandon(on_closed: Callable[[], None]) -> None` — worker `abandon`, and on exit: close the sink (echo flush), close the loaded transcriber, `finalize_wavs()`, then `on_closed()`.
  - `RecordingSession.stop_capture() -> threading.Event` — sources stop, `capture_ended_at` + `captured` written, PortAudio released, status `finalizing`, pipeline abandoned; returns an event set when the pipeline closed (also releases the session's `LIVE` gate lease).
  - `bootstrap.build_processing_job(settings, store, audio, observer, session_id, *, repair: bool, closed: threading.Event | None, gate_usage: GpuUsage) -> ProcessingJob` — steps: `repair` (if `repair`), `transcribe` (`OfflineTranscription.run`, gpu = usage.speech, weight = 2 + 60 × remaining / duration), `finalize`/`mix` (gpu False, weight 1), `diarize` (gpu = usage.speakers, weight 25, skipped when disabled), `minutes` (gpu = usage.llm, 30, skipped when off), `action_items` (gpu = usage.llm, 10), `index` (1); `before` = `closed.wait()`.
  - `SessionManager(…, queue: ProcessingQueue, job_factory: Callable[[str, bool, threading.Event | None], ProcessingJob])`: `stop()` runs `stop_capture()` on a short-lived thread, then under the lock sets `_session = None` and enqueues `job_factory(id, False, closed)`; `start()` refuses only while `_session` is set; `busy` = `_session is not None or queue has pending`.

- [ ] **Step 1: Write the failing tests**

```python
def test_abandon_skips_backlog_and_flush_and_calls_on_exit(): ...
def test_abandon_during_model_load_returns_at_once(): ...  # load blocks on an Event
def test_stop_capture_returns_closed_event_and_writes_capture_ended_at(): ...
def test_manager_start_allowed_after_stop_while_job_pending(): ...
def test_manager_start_refused_until_stop_capture_released_the_slot(): ...  # Review Focus 2
def test_job_waits_for_abandoned_pipeline_before_transcribing(): ...       # Review Focus 1
    # fake pipeline closes its sink 0.2 s later; transcribe step observes the sink closed
def test_stop_while_model_loading_still_yields_a_full_transcript(): ...     # fake slow factory; offline step transcribes from 0
def test_build_processing_job_steps_and_gpu_flags(): ...  # minutes off / diarization off variants
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `RecordingSession.stop()` (CLI `record`) keeps working by calling `stop_capture()` then running the same job synchronously (helper `run_job_inline(job)` in `processing/job.py`), so the CLI output is unchanged.
- [ ] **Step 4:** Full engine suite → PASS (existing `stop()` tests may need the inline job).
- [ ] **Step 5:** Commit `feat(engine): free the recorder at stop and finish meetings in the queue`.

### Task 7: Restart and recovery go through the queue

**Files:**
- Modify: `engine/src/vozata/storage/recovery.py` (`SessionRecovery.repair(session_id) -> float` public; `find_interrupted` skips sessions with `capture_ended_at`), `engine/src/vozata/api/session_manager.py` (`resume_pending()`, `recover()` enqueues), `engine/src/vozata/api/app.py` (call `resume_pending()` at startup, before the migration job), `engine/src/vozata/bootstrap.py`, `docs/roadmap/architecture.md` §6 (crash recovery), `docs/roadmap/api-contract.md` (`/recover`: 202 and enqueue; `session_already_active` no longer for processing; `capture_ended_at`)
- Test: `engine/tests/storage/test_recovery.py`, `engine/tests/api/test_recover.py`, `engine/tests/api/test_session_manager.py`

**Interfaces:**
- Consumes: Task 6 (`build_processing_job(..., repair=True, closed=None)`).
- Produces: `SessionManager.resume_pending() -> list[str]` — every session `finalizing` with `capture_ended_at` and not live, oldest first, enqueued with `repair=True`; returns their ids. `recover(id)` → enqueue with `repair=True` (still `SessionNotInterruptedError` for other statuses); the `repair` step runs `SessionRecovery.repair` and on `StoreRepairError` stores `recovery_error`, marks the session `interrupted` and ends the job `failed`.

- [ ] **Step 1: Write the failing tests**

```python
def test_resume_pending_enqueues_finalizing_sessions_with_capture_ended_oldest_first(): ...
def test_finalizing_without_capture_ended_is_still_interrupted(): ...
def test_recover_enqueues_instead_of_taking_the_slot(): ...  # start() succeeds during a recovery
def test_repair_failure_marks_interrupted_and_fails_the_job(): ...
def test_resumed_job_transcribes_from_the_last_committed_segment(): ...  # with a half-written last line (file backend)
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(engine): resume unfinished meetings and run recovery in the queue`.

### Task 8: API surface, events and other model users

**Files:**
- Modify: `engine/src/vozata/api/payloads.py` (`processing` on summary and detail), `engine/src/vozata/api/app.py` (WS connect snapshot: one `processing` envelope per `queue.pending()` after the first `status`), `engine/src/vozata/api/session_manager.py` (`_check_not_live` also refuses `queue.contains(id)`), `engine/src/vozata/api/minutes_job.py` and `api/action_items_job.py` (enqueue a job of minutes / action items + index steps instead of their own thread), `engine/src/vozata/api/ask_job.py` (`gate.priority(GpuUser.ASK)` around the answer when `gpu_usage().llm`), `engine/src/vozata/connection_checks.py` (model tests inside `gate.priority(GpuUser.CHECK)`), `engine/src/vozata/bootstrap.py`, `engine/src/vozata/locales/{en,pt-BR,es}.toml`, `docs/roadmap/api-contract.md` (`processing` event row, `processing` field, `/minutes` and `/action-items` 202 enqueue)
- Test: `engine/tests/api/test_ws.py`, `test_sessions.py`, `test_session_delete.py`, `test_audio.py`, `test_minutes_job.py`, `test_action_items_job.py`, `test_ask.py`, `test_settings_test.py`

**Interfaces:**
- Consumes: `ProcessingQueue.pending/state/contains`, `ProcessingState.to_payload()` (Task 5).
- Produces: event `processing` with `data = state.to_payload()` and envelope `session_id`; summary/detail field `processing: {state, percent, step, position?} | null`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ws_connect_sends_processing_snapshot_after_status(): ...
def test_summary_has_processing_while_queued_and_null_after(): ...
def test_delete_and_delete_audio_refused_while_queued_then_allowed(): ...  # Review Focus 5
def test_regenerate_minutes_is_queued_behind_running_job(): ...
def test_ask_cancels_running_llm_step_and_the_step_is_redone(): ...
def test_connection_check_holds_check_priority(): ...
def test_rename_while_queued_survives_the_job(): ...  # the finisher re-reads meta before each write (SessionMeta.restore), never writes a stale title
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Full engine suite + ruff → PASS.
- [ ] **Step 5:** Commit `feat(api): report background processing and route other model jobs through the queue`.

### Task 9: UI client and recorder

**Files:**
- Modify: `ui/src/VozAta.Client/EngineEvents.cs` (parse `processing`), `ui/src/VozAta.Client/Dtos.cs` (`ProcessingInfo` record; `Processing` on `SessionSummary` and detail), `ui/src/VozAta.Desktop/ViewModels/RecorderPageViewModel.cs`, `ui/src/VozAta.Desktop/App.axaml.cs` (`GuardClosing`: no 10-minute finalize wait; waits only for `Recorder.Idle`)
- Test: `ui/tests/VozAta.Desktop.Tests/EngineEventsTests.cs`, `EngineClientTests.cs`, `RecorderPageViewModelTests.cs`

**Interfaces:**
- Produces: `record ProcessingInfo(string State, int Percent, string? Step, int? Position)`; `record ProcessingEvent(string SessionId, ProcessingInfo Info) : EngineEvent`.
- Recorder: `StopAsync` → `SetState(Idle)` once the 202 arrives; `OnStatus` ignores events whose `SessionId` differs from `Session.SessionId` once a session id is known (it still adopts `recording`/`paused` of an unknown session when idle).

- [ ] **Step 1:** Tests: `Parses_processing_event_with_and_without_position`, `Summary_deserializes_processing_or_null`, `Stop_returns_to_idle_when_engine_accepts`, `Status_of_another_session_does_not_change_state`, `Finalizing_status_of_stopped_session_keeps_idle`.
- [ ] **Step 2:** `dotnet test` → FAIL. **Step 3:** Implement. **Step 4:** `dotnet test` → PASS; `dotnet format --verify-no-changes`.
- [ ] **Step 5:** Commit `feat(ui): free the recorder when the engine accepts stop`.

### Task 10: Meetings and meeting page indicators

**Files:**
- Modify: `ui/src/VozAta.Desktop/ViewModels/MeetingRows.cs` (`IsLive` = recording or paused; `Processing` observable; `IsProcessing`, `ProcessingText`, `ShowsDoneCheck`), `MeetingsPageViewModel.cs` (apply `ProcessingEvent` to the matching row; `done` → row reload + `UnseenDone` marker), `SessionPageViewModel.cs` (header indicator; minutes/speakers tabs "being processed" while their step is pending; marker cleared on open), `Views/MeetingsPage.axaml`, `Views/SessionPage.axaml`, `Resources/Strings*.resx`
- Create: `ui/src/VozAta.Desktop/ViewModels/ProcessingMarkers.cs` (`IProcessingMarkers` service: `MarkDone(id)`, `IsUnseen(id)`, `Clear(id)`; in-memory, registered in `App.axaml.cs`)
- Test: `MeetingsPageViewModelTests.cs`, `SessionPageViewModelTests.cs`, `ProcessingMarkersTests.cs`, locale parity test (existing)

**Interfaces:**
- Consumes: `ProcessingEvent`, `ProcessingInfo` (Task 9).
- Strings (en / pt-BR / es): `Processing_Queued` "Queued ({0})" / "Na fila ({0})" / "En cola ({0})"; `Processing_Running` "Processing {0} %" / "Processando {0} %" / "Procesando {0} %"; `Processing_Paused` "Paused" / "Pausado" / "En pausa"; `Processing_Done` "Ready" / "Pronto" / "Listo"; `Processing_TabPending` "This part is still being processed." / "Esta parte ainda está sendo processada." / "Esta parte todavía se está procesando.".
- Visuals: badge uses design tokens (phase 34); running = accent with %; done = success green check, no %.

- [ ] **Step 1:** Tests: `Row_shows_queued_position`, `Row_percent_follows_events`, `Row_done_shows_green_check_without_percent_until_opened`, `Finalizing_row_is_not_pinned_as_live`, `Session_page_tabs_pending_until_their_step_passes`, `Opening_meeting_clears_unseen_marker`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS + format.
- [ ] **Step 5:** Commit `feat(ui): show processing progress on meetings`.

### Task 11: Shell indicator and closing with pending work

**Files:**
- Create: `ui/src/VozAta.Desktop/ViewModels/ProcessingIndicatorViewModel.cs`
- Modify: `Views/ShellView.axaml` (under the recording indicator), `MainViewModel.cs` (route `ProcessingEvent`; `PendingProcessing` count), `App.axaml.cs` (`GuardClosing`: if `PendingProcessing > 0`, show the message dialog once, then close), `Resources/Strings*.resx`
- Test: `ProcessingIndicatorViewModelTests.cs`, `MainViewModelTests.cs`

**Interfaces:**
- Strings: `ProcessingIndicator_Text` "Processing {0} meeting(s) · {1} %" / "Processando {0} reunião(ões) · {1} %" / "Procesando {0} reunión(es) · {1} %"; `ProcessingIndicator_Queued` "+{0} queued" / "+{0} na fila" / "+{0} en cola"; `Close_PendingProcessing` "{0} meeting(s) are still being processed. Processing resumes the next time VozAta opens." / "{0} reunião(ões) ainda está(ão) sendo processada(s). O processamento continua na próxima vez que o VozAta abrir." / "{0} reunión(es) todavía se está(n) procesando. El procesamiento continúa la próxima vez que se abra VozAta.".

- [ ] **Step 1:** Tests: `Indicator_hidden_when_queue_empty`, `Indicator_shows_running_percent_and_queued_count`, `Close_with_pending_processing_warns_once_and_closes`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS + format.
- [ ] **Step 5:** Commit `feat(ui): add the processing indicator and the close warning`.

### Task 12: Full suites, manual check, phase done

- [ ] **Step 1:** Engine: `../.venv/Scripts/python -m pytest -q --cov=vozata` → all pass, coverage ≥ 80 % on the diff; ruff check + format clean.
- [ ] **Step 2:** UI: `dotnet test` → all pass; `dotnet format --verify-no-changes` clean.
- [ ] **Step 3:** Manual check on a scratch database (`DATABASE_PATH` override, never `C:/VozAta/vozata.db`), driving the app through UI Automation: record 30 s, Stop → Start enabled within 2 s; record a second meeting while the first processes; stop three in a row → order and "Queued (n)"; with local Ollama, start a live recording during the first meeting's minutes → "Paused", then finishes after Stop; close the app with a non-empty queue → warning; reopen → the queue resumes and finishes with full transcripts.
- [ ] **Step 4:** Tick the phase's acceptance criteria, set status `done` in `docs/roadmap/README.md`, Progress → `ready for PR`; record the manual check in *Decisions and notes*.
- [ ] **Step 5:** Commit `docs(roadmap): finish phase 40`; push; then the PR flow (`pr-ready` → `pr-open`; the user merges).
