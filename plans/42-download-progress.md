# Phase 42 — Model Download Progress Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While any model downloads from Hugging Face, the desktop app shows a full-width bar at the bottom of the page area with "Downloading speech model large-v3-turbo — 45 % (720 MB of 1.6 GB)" centered over it; it disappears when the download ends.

**Architecture:** A `ModelDownloader` port (Hugging Face implementation) makes sure a repo snapshot is in the local cache before a model loads: cached → returns its path without network; otherwise it sizes the files (`HfApi.model_info(files_metadata=True)`, filtered by the same `allow_patterns` the library uses) and runs `snapshot_download` with a byte-counting `tqdm_class`, reporting to a `DownloadTracker` that publishes a throttled `download_progress` WebSocket event (and a snapshot on connect). Faster-whisper then loads from the returned folder; Opus-MT downloads through it; the pyannote repos are pre-downloaded in the engine before the diarizer / embedder child starts, so the child finds them in the cache. The UI shows a `DownloadBarViewModel` docked at the bottom of the shell.

**Tech Stack:** Python 3.13 (huggingface_hub 2.2.0, faster-whisper 1.2.1, FastAPI, pytest), C# .NET 10 / Avalonia 12.

**Spec:** `docs/roadmap/phases/42-download-progress.md` — amended in Task 0 by the rulings below (read both).

## Rulings (from the code map, 2026-10-20)

- **No resume**: huggingface_hub 2.2.0 writes each file to a unique `.{uuid}.incomplete` and deletes it on failure, so a download interrupted by closing the app restarts from 0 the next time the model is needed; the bar shows it from 0. The spec's "resumes from the partial files" criterion and its `.incomplete` note change accordingly.
- **pyannote downloads in a child process with no progress channel**: the engine pre-downloads `pyannote/speaker-diarization-community-1` and `pyannote/wespeaker-voxceleb-resnet34-LM` (with `HF_TOKEN`) through the downloader before spawning the diarizer / embedder child; the child then loads from the cache. No child protocol change.
- **`HF_HUB_DISABLE_XET`**: huggingface_hub reads it once at first import; today's `setdefault` in `FasterWhisperTranscriber.__init__` is too late under `serve`. Set it at the very start of `vozata.__main__` (before any import that pulls huggingface_hub), keep the existing intent (XET off), and remove the late `setdefault`.
- **Offline** (`HF_HUB_OFFLINE=1`) or an already cached repo: no network call, no event.

## Global Constraints

- English only in code, comments, docs, commits, branch names and log messages.
- User-facing strings from locales: engine `src/vozata/locales/{en,pt-BR,es}.toml`, UI `Resources/Strings{,.pt-BR,.es}.resx`; every key in all three.
- Ports are `Protocol`s in `ports.py`; concrete classes wired only in `bootstrap.py` / `bootstrap_processing.py` and `App.axaml.cs`. `config.py` is the only module that reads environment variables (setting `HF_HUB_DISABLE_XET` in `__main__` is a process setup write, documented there).
- Unit tests never touch the network, GPU, audio or real models: fake the hub functions (`snapshot_download`, `model_info`, cache lookup) and the tracker clock. engine/tests fail the session if the real `engine/.env` changes or a non-daemon thread leaks.
- Modules near ~200 lines; diff coverage ≥ 80 %; LF line endings.
- Branch `feature/42-download-progress`; one logical change per commit with the Progress note; **commits stay local — push only when opening the PR** (user rule: save GitHub Actions minutes).
- Conventional Commits in English, **no `Co-Authored-By` trailer**.
- Engine: `../.venv/Scripts/python -m pytest -q` (redirect output to a file), `ruff check` / `ruff format`. UI: `dotnet test`, `dotnet format --verify-no-changes`.
- Contract changes in `docs/roadmap/api-contract.md` / `architecture.md` in the task that makes them.
- Strings (verbatim): kinds en "speech" / "speakers" / "translation", pt-BR "de fala" / "de locutores" / "de tradução", es "de voz" / "de hablantes" / "de traducción"; label en "Downloading {kind} model {model} — {percent} % ({done} of {total})", pt-BR "Baixando modelo {kind} {model} — {percent} % ({done} de {total})", es "Descargando modelo {kind} {model} — {percent} % ({done} de {total})"; unknown total en "Downloading {kind} model {model} — {done}", pt-BR "Baixando modelo {kind} {model} — {done}", es "Descargando modelo {kind} {model} — {done}"; two or more en "Downloading {count} models — {percent} % ({done} of {total})", pt-BR "Baixando {count} modelos — {percent} % ({done} de {total})", es "Descargando {count} modelos — {percent} % ({done} de {total})"; failure toast en "Downloading the {kind} model {model} failed: {reason}", pt-BR "Falha ao baixar o modelo {kind} {model}: {reason}", es "No se pudo descargar el modelo {kind} {model}: {reason}". Sizes as MB/GB with one decimal for GB.

## Review Focus

1. **A model already in the cache** (the common case on every start): no network call, no event, load time unchanged (pinned in Task 1).
2. **Network lost mid-download**: one `failed` event, the bar hides, an error toast; the existing load failure path (`model_failed`, `TranslationError`, `DiarizationError`) follows unchanged (pinned in Tasks 1 and 3).
3. **Two downloads at once** (speech model for a live session + translation model): one bar with the sum and "2 models"; each `done` removes its part (pinned in Tasks 1 and 3).
4. **The GPU→CPU fallback** of faster-whisper downloads a second repo (`WHISPER_CPU_MODEL`): it goes through the downloader too and shows its own bar (pinned in Task 2).
5. **A UI that connects mid-download** (window restored from the tray, app reopened while the engine still runs): the connect snapshot shows the bar at the current percent (pinned in Tasks 2 and 3).

---

### Task 0: Branch, phase start, spec amendment

**Files:** `docs/roadmap/README.md` (row 42 in progress), `docs/roadmap/phases/42-download-progress.md` (Progress section; amend the resume criterion, the `.incomplete` note and the pyannote / XET points with the Rulings above), `plans/42-download-progress.md`.

- [ ] **Step 1:** `git switch -c feature/42-download-progress` from up-to-date `main`.
- [ ] **Step 2:** Commit `docs(roadmap): plan and start phase 42` (local, no push).

### Task 1: Downloader and tracker

**Files:**
- Create: `engine/src/vozata/models/__init__.py`, `engine/src/vozata/models/download.py` (`HubDownloader`), `engine/src/vozata/models/tracker.py` (`DownloadTracker`)
- Modify: `engine/src/vozata/ports.py` (`ModelDownloader`), `engine/src/vozata/__main__.py` (`os.environ.setdefault("HF_HUB_DISABLE_XET", "1")` first), `engine/src/vozata/transcription/faster_whisper.py` (drop the late setdefault)
- Test: `engine/tests/models/test_download.py`, `engine/tests/models/test_tracker.py`, `engine/tests/test_cli.py` (XET set before hub import)

**Interfaces:**
- Produces:
  - `domain.ModelKind(StrEnum)`: `SPEECH = "speech"`, `SPEAKERS = "speakers"`, `TRANSLATION = "translation"`.
  - `ports.ModelDownloader(Protocol)`: `def ensure(self, kind: ModelKind, repo_id: str, *, allow_patterns: Sequence[str] | None = None, token: str | None = None) -> Path` — returns the snapshot folder; raises the hub's exception on failure (callers keep their own error paths).
  - `DownloadState` frozen dataclass `kind, model, downloaded_bytes: int, total_bytes: int | None, state: Literal["running", "done", "failed"]`, `to_payload() -> dict`.
  - `DownloadTracker(publish: Callable[[DownloadState], None], clock=time.monotonic, interval: float = 0.5)`: `start(kind, model, total) -> Handle`, `Handle.advance(n)`, `Handle.done()`, `Handle.failed(reason)`; `running() -> list[DownloadState]` (connect snapshot); thread-safe; publishes `running` at most every `interval` per download plus every state change; `failed` carries `reason` in the payload.
  - `HubDownloader(tracker, offline: bool, hub: HubFunctions | None = None)` where `HubFunctions` bundles `snapshot_download`, `model_info` (injectable for tests): cached check = `snapshot_download(repo_id, allow_patterns=…, local_files_only=True, token=…)` (no event); offline → that same call (its exception propagates); otherwise total = sum of `model_info(repo_id, files_metadata=True, token=…).siblings` sizes matching `allow_patterns` (None when unknown), then `snapshot_download(..., tqdm_class=<byte counter bound to the handle>)`. The byte counter must accept huggingface_hub 2.2.0's calls (`tqdm(total=…, unit="B", …)`, `.update(n)`, `.total` reassigned, `close()`), counting only byte bars (`unit == "B"`).

- [ ] **Step 1: Write the failing tests**

```python
def test_cached_repo_returns_its_path_without_network_or_events(): ...   # Review Focus 1: model_info never called; publish never called
def test_offline_does_not_download_and_propagates_the_hub_error(): ...
def test_download_reports_running_then_done_with_bytes_and_total(): ...  # fake snapshot_download drives the tqdm_class with 3 chunks
def test_total_counts_only_files_matching_allow_patterns(): ...
def test_unknown_total_is_reported_as_none(): ...
def test_failure_reports_failed_with_the_reason_and_reraises(): ...      # Review Focus 2
def test_tracker_throttles_running_events_per_download(): ...            # fake clock, interval 0.5
def test_tracker_keeps_two_downloads_apart_and_lists_running(): ...      # Review Focus 3
def test_main_sets_hf_hub_disable_xet_before_importing_the_hub(): ...    # subprocess-free: inspect order / env after importing vozata.__main__
```

- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS; full suite; ruff.
- [ ] **Step 5:** Commit `feat(engine): download models through a progress-reporting downloader`.

### Task 2: Wire the downloads and the event

**Files:**
- Modify: `engine/src/vozata/transcription/faster_whisper.py` (resolve the repo id with faster_whisper's own mapping — `faster_whisper.utils._MODELS`, names containing `/` used as is, existing folders used as is — then `downloader.ensure(SPEECH, repo, allow_patterns=<faster_whisper's list>)` and `WhisperModel(<folder>, …)`; same for the CPU fallback model), `engine/src/vozata/translation/opus_mt.py` (`hub_locator(download=lambda repo: downloader.ensure(TRANSLATION, repo))`), `engine/src/vozata/bootstrap.py` (one `DownloadTracker` publishing `download_progress` through the broadcaster, one `HubDownloader` passed to the transcriber / translator providers and to the diarizer / embedder factories, which call `ensure(SPEAKERS, <repo>, token=settings.hf_token)` before spawning their child), `engine/src/vozata/bootstrap_processing.py` (queue transcriber uses the same providers), `engine/src/vozata/api/app.py` (connect snapshot: one `download_progress` per running download, after the processing snapshot), `engine/src/vozata/api/container.py`, `engine/src/vozata/locales/*.toml` (nothing new unless messages are needed), `docs/roadmap/api-contract.md` (`download_progress` row), `docs/roadmap/architecture.md` (downloader, models section)
- Test: `engine/tests/transcription/test_faster_whisper_download.py`, `engine/tests/translation/test_opus_mt.py`, `engine/tests/diarization/test_subprocess_diarizer.py` / `test_subprocess_embedder.py` (pre-download before spawn), `engine/tests/api/test_ws.py`, `engine/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: event `download_progress` (envelope `session_id` null) with `{kind, model, downloaded_bytes, total_bytes, state, reason?}`; `ApiContainer.downloads: DownloadTracker`.

- [ ] **Step 1:** Tests: `test_whisper_loads_from_the_downloaded_folder`, `test_whisper_cpu_fallback_downloads_its_own_repo` (Review Focus 4), `test_existing_model_folder_skips_the_downloader`, `test_opus_mt_downloads_through_the_downloader`, `test_diarizer_predownloads_both_pyannote_repos_with_the_token_before_spawning`, `test_ws_connect_sends_running_downloads` (Review Focus 5), `test_download_events_are_published_with_null_session`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite + ruff → PASS.
- [ ] **Step 5:** Commit `feat(engine): report model downloads as download_progress events`.

### Task 3: UI bottom bar

**Files:**
- Modify: `ui/src/VozAta.Client/EngineEvents.cs` (`DownloadProgressEvent(string Kind, string Model, long DownloadedBytes, long? TotalBytes, string State, string? Reason)`), `ui/src/VozAta.Desktop/ViewModels/MainViewModel.cs` (route; clear on connection lost; `failed` → toast), `ui/src/VozAta.Desktop/Views/ShellView.axaml` (bar `DockPanel.Dock="Bottom"` in the page area, before the page content: `ProgressBar` with the label centered over it, design tokens only, `IsIndeterminate` when the total is unknown), `ui/src/VozAta.Desktop/App.axaml.cs` (DI), resources (strings in Global Constraints)
- Create: `ui/src/VozAta.Desktop/ViewModels/DownloadBarViewModel.cs`
- Test: `ui/tests/VozAta.Desktop.Tests/DownloadBarViewModelTests.cs`, `EngineEventsTests.cs`, `MainViewModelTests.cs`

**Interfaces:**
- Produces: `DownloadBarViewModel` with `IsVisible`, `Percent` (0–100), `IsIndeterminate`, `Text`; `OnProgress(DownloadProgressEvent)`, `OnConnectionLost()`, `RefreshTexts()` (language change).

- [ ] **Step 1:** Tests: `Hidden_without_downloads`, `Shows_kind_model_percent_and_sizes`, `Unknown_total_is_indeterminate_with_size_only`, `Two_downloads_show_one_summed_bar`, `Done_removes_its_part_and_hides_when_empty`, `Failed_hides_and_raises_a_toast` (Review Focus 2), `Connection_lost_clears`, `Language_change_refreshes_the_text`, `Parses_download_progress_with_and_without_total`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full UI suite + format → PASS.
- [ ] **Step 5:** Commit `feat(ui): show model downloads in a bottom progress bar`.

### Task 4: Full suites, manual check, phase done

- [ ] **Step 1:** Engine suite with coverage (output to a file; it must exit on its own), ruff; UI suite, format.
- [ ] **Step 2:** Manual check with an isolated Hugging Face cache (`HF_HOME=<scratch>\hf`, so the user's cache is untouched) and a small model (`WHISPER_MODEL=tiny`, ~75 MB), a scratch database, the app launched on it: start a recording → the bottom bar shows "Baixando modelo de fala tiny — N % (x de y)" growing, then disappears and the live transcript starts; restart with the cache filled → no bar. Capture only the app window (`PrintWindow`). Delete the scratch cache and database afterwards.
- [ ] **Step 3:** Tick the (amended) acceptance criteria, README `done`, Progress `ready for PR`; commit; push once; open the PR; the user merges.
