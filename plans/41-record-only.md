# Phase 41 — Live Transcription Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-recording "Live transcription" option: when off, the meeting only records audio, and after Stop the processing queue transcribes the whole recording, then runs speakers, minutes and action items.

**Architecture:** A new setting `LIVE_TRANSCRIPTION` (default `true`) is the default of a per-recording `live_transcription` flag carried by `POST /sessions` → `StartOptions` → `build_session` → `SessionComponents`, stored in `session.json`. With the flag off, `CapturePipeline` runs in audio-only mode (writers and level meters only, no chunkers/worker/stitchers/echo/partials) and `RecordingSession` skips live translation and live speakers, so no model loads and the GPU gate is never held. Phase 40's `transcribe` step already starts at 0 when the raw transcript is empty, so the queue needs no change.

**Tech Stack:** Python 3.13 (FastAPI, numpy, pytest), C# .NET 10 / Avalonia 12 (CommunityToolkit.Mvvm, xUnit).

**Spec:** `docs/roadmap/phases/41-record-only.md` (read it first). Note: the spec's Scope puts the transcribe-from-0 change in `processing/job.py`; since phase 40 the step lives in `processing/session_job.py` and already starts at 0 for an empty transcript (resume points 0.0, weight 62) — no change there, only tests.

## Global Constraints

- English only in code, comments, docs, commits, branch names and log messages.
- Every user-facing string comes from locales: engine `src/vozata/locales/{en,pt-BR,es}.toml`, UI `Resources/Strings{,.pt-BR,.es}.resx`; every new key in all three (parity tests enforce it; `LocalizationResourcesTests.Every_engine_setting_has_a_label_and_help_text` reads `engine/.env.example`).
- Ports are `Protocol`s in `ports.py`; concrete classes are wired only in `bootstrap.py` / `bootstrap_processing.py` (engine) and `App.axaml.cs` (UI).
- Unit tests never touch audio hardware, GPU, network or real LLMs; use `tests/fakes.py` fakes. engine/tests fail the session if the real `engine/.env` changes: tests that save settings use a tmp env file.
- Modules stay near ~200 lines; one responsibility per module.
- Diff coverage ≥ 80 %; every new class, branch and bug fix has tests.
- LF line endings; never commit CRLF.
- Branch `feature/41-record-only`; one logical change per commit; every commit also updates the phase file's **Progress** and is pushed.
- Commit messages: Conventional Commits, English, **no `Co-Authored-By` trailer**.
- Engine commands from `engine/`: `../.venv/Scripts/python -m pytest -q`, `../.venv/Scripts/ruff check src tests`, `../.venv/Scripts/ruff format src tests`. UI from `ui/`: `dotnet test`, `dotnet format --verify-no-changes`.
- Shared contract changes go into `docs/roadmap/api-contract.md` / `architecture.md` (§8 `session.json`, §9 config keys) in the task that makes them.
- Strings (verbatim): checkbox label en "Live transcription", pt-BR "Transcrição simultânea", es "Transcripción simultánea"; audio-only notice en "Recording audio only. The transcript is created after you stop.", pt-BR "Gravando apenas o áudio. A transcrição é criada depois que você parar.", es "Grabando solo el audio. La transcripción se crea cuando detengas la grabación."

## Review Focus

1. **Pause / resume during an audio-only recording**: the WAVs get silence while paused and the offline transcription later skips it; no error from a pipeline without chunkers (pinned in Task 2).
2. **Stop of an audio-only meeting**: `closed` is set at once (no worker to wait for), the next recording's model load does not wait, and the queued job transcribes from 0 (pinned in Task 2).
3. **An audio-only recording never holds the GPU gate**: a queued meeting's GPU step keeps running while it records (pinned in Task 2).
4. **Translation chosen together with audio-only** (request carries `translate_to` and `live_transcription: false`): no translation worker starts and no error is raised (pinned in Task 2).
5. **Recovery of an audio-only meeting after a crash during capture**: the resumed job transcribes the whole recording (pinned in Task 2).

---

### Task 0: Branch and phase start

**Files:** `docs/roadmap/README.md` (row 41 → `in progress (\`feature/41-record-only\`)`), `docs/roadmap/phases/41-record-only.md` (append **Progress**; steps = Tasks 1–5), `plans/41-record-only.md` (this plan).

- [ ] **Step 1:** `git switch -c feature/41-record-only` from an up-to-date `main`.
- [ ] **Step 2:** Commit `docs(roadmap): plan and start phase 41`; push with `-u`.

### Task 1: `LIVE_TRANSCRIPTION` setting and the per-recording option

**Files:**
- Modify: `engine/src/vozata/config.py` (`Settings.live_transcription: bool = True`, parsed with `_flag(raw, "LIVE_TRANSCRIPTION", True)`), `engine/src/vozata/settings_fields.py` (`Field("LIVE_TRANSCRIPTION", "live_transcription", "bool", group="transcription")`), `engine/.env.example` (comment + `LIVE_TRANSCRIPTION=true`), `engine/src/vozata/api/schemas.py` (`StartSession.live_transcription: bool | None = None`), `engine/src/vozata/api/routes/sessions.py`, `engine/src/vozata/api/session_manager.py` (`StartOptions.live_transcription: bool | None = None`), `engine/src/vozata/bootstrap.py` (`session_factory` passes it; `build_session(..., live_transcription: bool | None = None)`; `None` = `settings.live_transcription`), `engine/src/vozata/session.py` (`SessionComponents.live_transcription: bool = True`), `engine/src/vozata/session_meta.py` (stores `live_transcription` at start, always), `ui/src/VozAta.Desktop/Resources/Strings*.resx` (`Setting_LIVE_TRANSCRIPTION` "Live transcription by default" / "Transcrição simultânea por padrão" / "Transcripción simultánea por defecto"; `SettingHelp_LIVE_TRANSCRIPTION` "Off: new recordings only record audio and are transcribed after you stop." / "Desligado: novas gravações apenas gravam o áudio e são transcritas depois que você parar." / "Desactivado: las nuevas grabaciones solo graban el audio y se transcriben al detenerlas."), `docs/roadmap/architecture.md` §8 (`live_transcription` in `session.json`) and §9 (key row), `docs/roadmap/api-contract.md` (`POST /sessions` body `live_transcription?: bool`, omitted = `LIVE_TRANSCRIPTION`)
- Test: `engine/tests/test_config.py`, `engine/tests/api/test_sessions.py`, `engine/tests/test_bootstrap.py`, `engine/tests/test_session.py` (meta), UI `LocalizationResourcesTests` (existing, must pass)

**Interfaces:**
- Produces: `Settings.live_transcription: bool`; `StartOptions.live_transcription: bool | None`; `build_session(..., live_transcription: bool | None = None)`; `SessionComponents.live_transcription: bool` (default `True`); `session.json` key `live_transcription: bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_live_transcription_defaults_to_true_and_reads_the_key(): ...   # load_settings(env={}) → True; {"LIVE_TRANSCRIPTION": "false"} → False
def test_start_passes_live_transcription_to_the_factory(): ...           # POST /sessions {"live_transcription": false} → StartOptions(live_transcription=False); omitted → None
def test_build_session_uses_the_setting_when_the_option_is_none(): ...  # components.live_transcription mirrors settings when None, the option otherwise
def test_session_json_records_live_transcription(): ...                  # meta["live_transcription"] is False for an audio-only start, True otherwise
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (plumbing only; behavior comes in Task 2). **Step 4:** Engine suite + ruff; UI suite (parity test) → PASS.
- [ ] **Step 5:** Commit `feat(engine): add the live transcription option and its default setting`.

### Task 2: Audio-only capture

**Files:**
- Modify: `engine/src/vozata/session_pipeline.py` (`CapturePipeline(..., live: bool = True)`), `engine/src/vozata/session.py` (`start()` with `components.live_transcription` False: `CapturePipeline(..., live=False)`, no `_live_translation()`, no `_live_embedder()`, no `start_transcription()`; `stop_capture()` still writes `capture_ended_at` and returns `closed`)
- Test: `engine/tests/test_session_pipeline.py`, `engine/tests/test_session.py`, `engine/tests/test_session_gpu.py`, `engine/tests/test_bootstrap_processing.py`, `engine/tests/api/test_session_manager.py`

**Interfaces:**
- Consumes: Task 1 `SessionComponents.live_transcription`.
- Produces: `CapturePipeline(..., live: bool = True)`. With `live=False`: tracks hold only writers (no chunker, stitcher, worker, echo filter, partials, live speakers, transcript sink opened); `receiver()` writes and reports levels; `set_paused()` pauses writers; `stop_capture()` stops accepting; `abandon(on_closed)` finalizes the WAVs and calls `on_closed` on the caller's thread; `transcriber` is None; `echo_dropped` is None. `start_transcription()` must not be called (raise `RuntimeError` if it is).

- [ ] **Step 1: Write the failing tests**

```python
def test_audio_only_pipeline_writes_and_reports_levels_without_transcribing(): ...  # factory never called; writer got samples; observer.on_level called
def test_audio_only_pipeline_pauses_writers(): ...                                   # Review Focus 1
def test_audio_only_abandon_finalizes_wavs_and_closes_at_once(): ...                 # on_closed called synchronously; writers finalized to equal length
def test_audio_only_session_loads_no_model_and_never_holds_the_gate(): ...           # Review Focus 3: transcriber/embedder factories not called; gate.priority_held False throughout
def test_audio_only_session_ignores_translation(): ...                               # Review Focus 4: translate_to set → no translator factory call, no error event
def test_audio_only_stop_sets_closed_at_once_and_the_job_transcribes_from_zero(): ...  # Review Focus 2: closed.is_set() right after stop_capture; job's transcribe step feeds from 0.0 (fake transcriber sees both channels from t=0)
def test_resumed_audio_only_meeting_is_transcribed_whole(): ...                      # Review Focus 5: finalizing + capture_ended_at, empty transcript → resume_pending job writes segments covering the recording
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; keep `transcriber_factory` in the components (the CLI's inline job uses it offline). **Step 4:** Full engine suite + ruff → PASS.
- [ ] **Step 5:** Commit `feat(engine): record audio only when live transcription is off`.

### Task 3: `python -m vozata transcribe <id>`

**Files:**
- Create: `engine/src/vozata/cli/transcribe.py`
- Modify: `engine/src/vozata/__main__.py` (subcommand `transcribe` with a positional session folder/id like `recover <dir>`), `engine/src/vozata/locales/{en,pt-BR,es}.toml` (`cli.transcribe_*` messages)
- Test: `engine/tests/cli/test_transcribe.py`

**Interfaces:**
- Consumes: `OfflineTranscription(...).run(session_id, token, on_progress)` (phase 40), the stored-meta language/vocabulary helpers used by `bootstrap_processing.build_processing_job`.
- Produces: `run_transcribe(target: str, settings: Settings, console, build: Callable[...]) -> int` — transcribes what the stored raw transcript does not cover (all of it for an audio-only meeting), prints progress in 10 % steps and the number of new segments; exit 0 on success, 1 for an unknown session or a session still recording (`status` recording/paused). It does not run diarization or minutes.

- [ ] **Step 1:** Tests: `test_transcribe_writes_the_missing_segments_and_reports_progress`, `test_transcribe_of_a_fully_transcribed_meeting_adds_nothing`, `test_transcribe_refuses_an_unknown_or_recording_session` (fake transcriber, tmp store).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit `feat(cli): transcribe a stored meeting from its audio`.

### Task 4: UI checkbox, preference and notices

**Files:**
- Modify: `ui/src/VozAta.Client/Dtos.cs` (`StartSessionRequest` gains `bool? LiveTranscription` with `[JsonIgnore(WhenWritingNull)]`), `ui/src/VozAta.Desktop/Services/UiPreferences.cs` (`UiPreferencesData.LiveTranscription: bool?`), `ui/src/VozAta.Desktop/ViewModels/RecorderPageViewModel.cs`, `ui/src/VozAta.Desktop/Views/RecorderPage.axaml`, `Resources/Strings*.resx` (`LiveTranscription` label, `TranscriptAudioOnly` notice — strings in Global Constraints)
- Test: `ui/tests/VozAta.Desktop.Tests/RecorderPageViewModelTests.cs` (or the existing recorder test class), `EngineClientTests.cs`

**Interfaces:**
- Produces: `RecorderPageViewModel.LiveTranscription: bool` (observable, editable only when `CanEditOptions`); `IsAudioOnlyNotice: bool` (true when `!LiveTranscription` and the transcript is empty); `CanChooseTranslation: bool` (= `CanEditOptions && LiveTranscription`).
- Rules: the default comes from `LIVE_TRANSCRIPTION` (`settings.GetString("LIVE_TRANSCRIPTION")` parsed as bool, default true); the last choice is saved in `ui.json` (`LiveTranscription`) and wins over the setting while it equals the choice made; saving a new `LIVE_TRANSCRIPTION` in Config (`OnSettingsSaved`, only when not recording) applies it and clears the remembered choice. `StartAsync` always sends `LiveTranscription`. When unchecked, the translation chip is disabled and the transcript placeholder shows `TranscriptAudioOnly` instead of `TranscriptEmpty`.
- View: a toggle chip `Button Classes="chip"` (same style as the other option chips, `IsEnabled="{Binding CanEditOptions}"`) placed first in the options WrapPanel, with a check icon state; `AutomationProperties.Name` = the label.

- [ ] **Step 1:** Tests: `Live_transcription_defaults_to_the_engine_setting`, `Remembered_choice_wins_and_is_saved`, `Saving_the_setting_resets_the_choice`, `Start_sends_live_transcription`, `Unchecked_disables_translation_and_shows_the_audio_only_notice`, `Option_is_read_only_while_recording`, `StartSessionRequest_serializes_live_transcription` (client).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full UI suite + `dotnet format --verify-no-changes` → PASS.
- [ ] **Step 5:** Commit `feat(ui): add the live transcription option to the recorder`.

### Task 5: Full suites, manual check, phase done

- [ ] **Step 1:** Engine suite with coverage, ruff check/format; UI suite, format check.
- [ ] **Step 2:** Manual check on a scratch database (`DATABASE_PATH` + `OUTPUT_DIR` overrides, `WHISPER_MODEL=large-v3`, `HF_HUB_OFFLINE=1`), driven through the engine API (the user may use the app meanwhile): `POST /sessions {"live_transcription": false}` 30 s → no `model_loading`/`segment` events during the recording (WebSocket), `nvidia-smi` memory unchanged; `POST /sessions/current/stop` → the job transcribes from 0 with `processing` percent driven by `transcribe`, then diarize/minutes/action items → `done` with transcript and minutes. Then the app: the checkbox, its persistence across a restart, the translation chip disabled, the audio-only notice (capture only the app window with `PrintWindow`).
- [ ] **Step 3:** Tick acceptance criteria, README status `done`, Progress `ready for PR` with the manual check notes; commit `docs(roadmap): finish phase 41`; push; PR flow (`pr-ready` → `pr-open`; the user merges).
