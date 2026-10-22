# Phase 44 — Worker: Server and Remote Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `vozata worker` command serves Whisper transcription on a GPU PC of the local network, behind a token; the engine's new `vozata_worker` speech provider uses it live and after Stop, and falls back to the local faster-whisper with a `worker_fallback` notice when the worker does not answer.

**Architecture:** The worker is a FastAPI app in `engine/src/vozata/worker/` started by a new CLI subcommand of the same package (so the same PyInstaller bundle ships it). It keeps one `FasterWhisperTranscriber` loaded and serializes requests. On the engine, `worker_client/` holds an httpx client (Bearer, one `/health` probe, retry) and `WorkerTranscriber` (the `Transcriber` port). One `build_transcriber()` in `bootstrap.py` replaces the three direct `_provider(TRANSCRIBERS, …)` calls and owns the fallback.

**Tech Stack:** Python 3.13 (FastAPI, uvicorn, httpx, numpy, pytest), C# .NET 10 / Avalonia (xUnit).

**Spec:** `docs/roadmap/phases/44-worker-speech.md`.

## Rulings

- **Same package, new subcommand**: `vozata worker [--check]`. `--check` loads nothing, prints the version and the resolved host/port, exits 0 (packaging smoke test).
- **Worker settings** come from the worker PC's own `.env` through `load_settings` (only `config.py` reads the environment): new keys `WORKER_HOST` (default `0.0.0.0`), `WORKER_PORT` (8766), `WORKER_TOKEN`; Whisper keys (`WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_CPU_MODEL`) are the existing ones.
- **Token**: required when the host is not loopback (`net.is_local_url` on `http://<host>`). Missing → the command generates `secrets.token_urlsafe(32)`, appends `WORKER_TOKEN=` to the `.env` in the working directory, prints it once (localized) and starts. Every route, `/health` included, needs `Authorization: Bearer <token>` (`hmac.compare_digest`); 401 otherwise.
- **Engine keys**: `WORKER_URL` (default empty = no worker), `WORKER_TOKEN` (secret, masked like the others). Group `worker` on the Config page.
- **Wire**: `POST /transcribe?language=<code|empty>` body `application/octet-stream` float32 LE mono 16 kHz; headers `X-Hints`, `X-Prompt` percent-encoded UTF-8 (optional). Reply `{"words":[{"text","start","end","probability"}],"language":str|null,"avg_logprob":float|null}`. An all-zero body is never sent by the client (empty result locally).
- **Probe**: the client calls `GET /health` once per client object with a 3 s timeout; `ConnectError` / `ConnectTimeout` / `ReadTimeout` → `WorkerUnreachableError(host)`; 401 → `WorkerAuthError` (a `ConfigError` on `WORKER_TOKEN`, not a fallback: a wrong token is a setup error the user must see). During transcription, connection errors after retries → `WorkerUnreachableError`.
- **Fallback at build**: `build_transcriber(settings, downloader, notices)` → for `vozata_worker`: build the client and probe; on `WorkerUnreachableError` call `notices.fallback("speech", host)` and return `FasterWhisperTranscriber(settings, downloader)`. Other providers: unchanged.
- **Fallback mid-session**: `WorkerTranscriber(client, local_factory, notices)`: on `WorkerUnreachableError` in `transcribe`, build the local transcriber once (`local_factory()`), notify, and transcribe that chunk locally; later chunks go local for the rest of this object's life.
- **Notices**: port `FallbackNotices.fallback(task: str, host: str) -> None`. API: publishes `error` with code `worker_fallback` and `localizer.t("errors.worker.fallback", task=localizer.t(f"worker.task.{task}"), host=host)`. CLI: the console prints the same text. Tests: a recording fake.
- **Gate**: `gpu_usage(settings, cuda, speech_remote=False)`; the session / job computes `speech_remote` from the resolved transcriber (`isinstance(t, WorkerTranscriber)`), so a fallback makes it local again.
- **`/health`**: `worker: {url, reachable, version} | null` (null when `WORKER_URL` is empty); `stt.device` = the worker host when `stt_provider == "vozata_worker"` (like `remote_host` for the OpenAI path).

## Global Constraints

- English in code, comments, docs, commits; user text from locales (`en`, `pt-BR`, `es` TOML and RESX), every key in all three.
- Ports in `ports.py`; concrete classes wired only in `bootstrap.py` / `App.axaml.cs`.
- Unit tests never touch GPU, network or real models: fake transcriber in the worker, `httpx.MockTransport` in the client, FastAPI `TestClient`.
- Commits local until the PR; each commit updates the phase **Progress**; diff coverage ≥ 80 %.

---

### Task 1: Worker settings, token auth, `/health`, `vozata worker`

**Files:** create `worker/__init__.py`, `worker/app.py`, `worker/auth.py`, `cli/worker.py`, tests `tests/worker/test_auth.py`, `tests/worker/test_health.py`, `tests/cli/test_worker.py`; modify `config.py` (`worker_host`, `worker_port`, `worker_token`, `worker_url`), `__main__.py`, `locales/*.toml`, `.env.example`.

- [ ] Failing tests: 401 without / with a wrong token, 200 with the right one; `/health` body `{version, gpu, capabilities: ["speech"], models: []}`; command refuses nothing on loopback without a token, generates and saves a token for `0.0.0.0` and prints it; `--check` exits 0 without loading a model.
- [ ] Implement; `ruff`; commit `feat(worker): serve /health behind a token with the vozata worker command`.

### Task 2: `/transcribe` with a kept faster-whisper

**Files:** create `worker/speech.py`, `tests/worker/test_transcribe.py`; modify `worker/app.py`.

- [ ] Failing tests (fake transcriber factory): samples, language, hints and prompt reach the transcriber unchanged; the reply carries probabilities and `avg_logprob`; the model is built once and reused; concurrent requests are serialized; a body that is not float32 (odd length) → 422; `/health` lists the loaded model after the first request.
- [ ] Implement (`SpeechService(factory)` with a lock); commit `feat(worker): transcribe with a kept Whisper model`.

### Task 3: Engine worker client and `WorkerTranscriber`

**Files:** create `worker_client/__init__.py`, `worker_client/client.py`, `worker_client/transcriber.py`, tests `tests/worker_client/test_client.py`, `tests/worker_client/test_transcriber.py`; modify `ports.py` (`WorkerUnreachableError` next to the other errors if shared, `FallbackNotices`).

- [ ] Failing tests: Bearer header; probe once; unreachable shapes → `WorkerUnreachableError` with the host; 401 → `ConfigError` on `WORKER_TOKEN`; retry on 503 then success; silence not sent; result mapping; `check_transcriber_contract` with a scripted worker; mid-session switch builds the local transcriber once, notifies once, and later chunks stay local; `close()` closes both.
- [ ] Implement; commit `feat(engine): transcribe through the VozAta worker`.

### Task 4: `build_transcriber`, fallback notice, gate rule

**Files:** modify `bootstrap.py` (registry entry, `build_transcriber`, the three call sites, notices wiring to the broadcaster / console), `bootstrap_processing.py`, `processing/gpu_gate.py`, `locales/*.toml`; tests in `tests/test_bootstrap.py`, `tests/test_bootstrap_processing.py`, `tests/processing/test_gpu_gate.py`.

- [ ] Failing tests: reachable worker → `WorkerTranscriber`, `speech_remote` true, no GPU priority taken by the live lease; unreachable → local transcriber, one `worker_fallback` error event with the host and the localized task, gate local again; the queue's transcribe step does the same; other providers untouched.
- [ ] Implement; commit `feat(engine): fall back to local speech when the worker does not answer`.

### Task 5: Settings, connection check, `/health.worker`, UI

**Files:** modify `settings_fields.py` (`WORKER_URL` url, `WORKER_TOKEN` secret, group `worker`), `connection_checks.py` (target `worker`), `api/routes/health.py`, `api/schemas.py`, `locales/*.toml`; UI `SettingsViewModel.cs` (`TestAnchors["WORKER_URL"] = ConnectionTargets.Worker`), `VozAta.Client/Config.cs` (`ConnectionTargets.Worker`), `SettingsViewModel` group order, resources (labels, help, group title, en / pt-BR / es); tests in `tests/api/test_health.py`, `tests/api/test_settings_test.py`, `tests/api/test_settings_get.py`, UI `ConfigPageViewModelTests`, `LocalizationResourcesTests`.

- [ ] Failing tests, implement, `dotnet test`, `dotnet format`; commit `feat: configure and test the worker from the Config page`.

### Task 6: Packaging, guide, contract docs

**Files:** `packaging/build.ps1` (smoke `vozata-engine.exe worker --check`), `docs/remote-worker.md` (new), `docs/remote-ollama.md`, `docs/INSTALL.md` (link), `docs/roadmap/worker-api.md` (new), `docs/roadmap/architecture.md` (§5 ports, §9 keys), `docs/roadmap/api-contract.md` (`/health.worker`, `worker_fallback`).

- [ ] Write; commit `docs: guide and API for the VozAta worker`.

### Task 7: Full suites, manual check, phase done

- [ ] Engine `pytest --cov` to a file (exits on its own), ruff; UI `dotnet test`, `dotnet format --verify-no-changes`.
- [ ] Manual (no second PC): scratch `.env` for a worker on this PC's LAN address with a token; scratch engine (port 8799, scratch data) with `STT_PROVIDER=vozata_worker` and `WORKER_URL` → transcription of a scratch meeting through the worker (the CLI `vozata transcribe <id>`), `/health.worker.reachable`; stop the worker → the next run falls back with the `worker_fallback` event. Close both processes afterwards.
- [ ] Tick the acceptance criteria, README `done`, Progress `ready for PR`; commit `docs(roadmap): finish phase 44`; push once, open the PR; the user merges.
