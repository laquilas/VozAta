# Phase 43 — Ollama on Another PC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minutes, action items and Ask can run on an Ollama server on another PC of the local network: the GPU gate stops treating it as local work, an unreachable server fails fast with a clear message, the Config page says transcripts leave this machine, and a guide explains the other PC's setup.

**Architecture:** One helper decides "local or remote" from `OLLAMA_URL` (`net.py`). `gpu_usage()` sets `llm=False` for a remote Ollama, which already flows to the queue steps, Ask and the Config check (they all read `usage(...).llm`). `OllamaLanguageModel` probes `/api/tags` once before its first request and raises `LlmUnreachableError` (a `LanguageModelError`) on connection failure; the minutes / action-items / Ask paths turn it into a localized `llm_unreachable` message. The UI decides "remote" for the note with the same rules while the user types.

**Tech Stack:** Python 3.13 (httpx, FastAPI, pytest), C# .NET 10 / Avalonia 12 (xUnit).

**Spec:** `docs/roadmap/phases/43-remote-ollama.md` (read it with this plan).

## Rulings (from the code map, 2026-10-21)

- **Local means loopback only**: `localhost` (any case, also `*.localhost`), `127.0.0.0/8`, `::1`. An empty or unparsable URL, and `0.0.0.0` / `::` (unspecified), count as local (conservative: the gate keeps its phase 40 behavior). A URL without a scheme (`192.168.0.20:11434`) is parsed as `http://…`. This PC's own LAN address is remote.
- **One switch for the gate**: `gpu_usage(settings, cuda).llm` is `False` for a remote Ollama. Queue minutes / action-items steps (`session_job._gpu`, `model_job`), `AskJob` (`uses_gpu=llm_on_gpu`) and the Config check (`check_priority`) all read it, so no other gate code changes.
- **Whisper stays loaded**: `free_whisper()` in `bootstrap.py` returns at once when Ollama is remote.
- **Probe once per model object**: before the first `generate()` / `stream()`, `GET /api/tags` with `AVAILABILITY_TIMEOUT` (3 s). `httpx.ConnectError`, `httpx.ConnectTimeout` or `httpx.ReadTimeout` on the probe → `LlmUnreachableError(host)`. An HTTP error status or bad JSON on the probe does not count (the chat call reports it as before). A `ConnectError` / `ConnectTimeout` during a chat call also raises `LlmUnreachableError` (server went away mid-job). Each job already builds its own model object, so a later retry probes again.
- **No release to a dead server**: after `LlmUnreachableError`, `release()` returns without a request (otherwise it would wait for the 300 s client timeout and hold the queue).
- **Event code**: when the cause is `LlmUnreachableError`, the `error` event code is `llm_unreachable` (instead of `minutes_failed` / `action_items_failed`) and the message is the context's `errors.llm_unreachable.*` string; Ask puts the `answer` message into its existing `error` field. Other failures keep their codes.
- **`/health`**: `llm.remote: bool` and `llm.host: str | null` (null when local or provider is not `ollama`), from `settings_file.current`.
- **Meeting page**: an `llm_unreachable` error for the meeting that is open is shown in its `Error` line (next to "Regenerate minutes") even when no regeneration is running; other codes keep today's rule (only while busy).
- **Config note**: computed in the UI from the `OLLAMA_URL` editor's text (live while typing) with a C# port of the same rules; no engine call.

## Global Constraints

- English only in code, comments, docs, commits, branch names and log messages.
- User-facing strings from locales: engine `src/vozata/locales/{en,pt-BR,es}.toml`, UI `Resources/Strings{,.pt-BR,.es}.resx`; every key in all three (parity tests exist).
- `config.py` is the only module that reads environment variables; concrete classes wired only in `bootstrap.py` / `App.axaml.cs`.
- Unit tests never touch the network, GPU, audio or a real LLM: `httpx.MockTransport` raising `httpx.ConnectError` / `ConnectTimeout` simulates the off PC. engine/tests fail the session if the real `engine/.env` changes or a non-daemon thread leaks; redirect pytest output to a file.
- Commits stay local until the PR; each commit updates the phase **Progress** section.
- Diff coverage ≥ 80 %; Mermaid for any diagram.

## Review Focus

1. **Release after an unreachable probe** must not send a request (a dead host would hang the queue up to 300 s) — test in Task 2.
2. **Server goes away mid-job** (probe OK, chat `ConnectError`) → `llm_unreachable`, not a generic failure — test in Task 2.
3. **Queue keeps going**: a meeting whose minutes step hit `llm_unreachable` ends `done` without minutes, its action-items step fails the same quick way, and the next queued meeting runs — test in Task 2 (finisher / queue level, fake LLM raising `LlmUnreachableError`).
4. **Switching `OLLAMA_URL` from remote back to localhost** at runtime (`PUT /settings`) makes the gate local again on the next step (it reads `settings_file.current`) — test in Task 1.
5. **URL shapes**: no scheme, upper-case `LOCALHOST`, `[::1]`, trailing path, `https://` — table tests in Task 1 (Python) and Task 3 (C#) with the same rows.

---

### Task 1: Local or remote — helper, GPU gate, Whisper release, `/health`

**Files:**
- Create: `engine/src/vozata/net.py`, `engine/tests/test_net.py`
- Modify: `engine/src/vozata/processing/gpu_gate.py` (`gpu_usage`), `engine/src/vozata/bootstrap.py` (`free_whisper`), `engine/src/vozata/api/schemas.py` (`LlmStatus`), `engine/src/vozata/api/routes/health.py`
- Test: `engine/tests/processing/test_gpu_gate.py`, `engine/tests/api/test_health.py` (or the file that tests `/health` today), `engine/tests/test_bootstrap.py`
- Docs: `docs/roadmap/api-contract.md` (`/health` `llm.remote`, `llm.host`), `docs/roadmap/architecture.md` (gate rule: remote Ollama is not local GPU work)

**Interfaces:**
- Produces: `net.is_local_url(url: str) -> bool`; `net.url_host(url: str) -> str` (hostname, or the raw text when none parses; no scheme → `http://` prefix); `net.remote_llm_host(settings: Settings) -> str | None` (host when `llm_provider == "ollama"` and the URL is not local, else None). `LlmStatus.remote: bool = False`, `LlmStatus.host: str | None = None`.

- [ ] **Step 1: Failing tests**
  - `test_is_local_url` parametrized: local → `http://localhost:11434`, `http://LOCALHOST:11434`, `http://foo.localhost`, `http://127.0.0.1:11434`, `http://127.1.2.3`, `http://[::1]:11434`, `localhost:11434`, `""`, `http://0.0.0.0:11434`; remote → `http://192.168.0.20:11434`, `192.168.0.20:11434`, `https://gpu-box.lan/ollama`, `http://10.0.0.5`, `http://[fe80::1]:11434`, `http://gpu-box:11434`.
  - `test_url_host`: `http://192.168.0.20:11434/x` → `192.168.0.20`; `gpu-box:11434` → `gpu-box`.
  - `test_remote_llm_host`: ollama + LAN URL → `"192.168.0.20"`; ollama + localhost → None; provider `fake` + LAN URL → None.
  - `test_gpu_usage_remote_ollama_is_not_local_gpu`: cuda True, ollama at `http://192.168.0.20:11434` → `usage.llm is False`; at localhost → True.
  - `test_free_whisper_skipped_for_remote_ollama` (bootstrap): with a shared Whisper fake and a remote URL, building the minutes generator does not call `release()`; with localhost it does.
  - `/health` test: remote URL → `llm.remote is True`, `llm.host == "192.168.0.20"`; localhost → `False`, `None`. After `PUT /settings` with `OLLAMA_URL=http://localhost:11434`, `/health` reports local again (Review Focus 4; the gate reads the same `settings_file.current`).
- [ ] **Step 2:** Run them — FAIL (`net` missing, fields missing).
- [ ] **Step 3:** Implement `net.py` (stdlib `urllib.parse` + `ipaddress`), then use `remote_llm_host` in `gpu_usage` (`llm = provider == "ollama" and cuda and remote_llm_host(settings) is None`), `free_whisper` (return when `remote_llm_host(settings_file.current)` is not None), and `health.py`.
- [ ] **Step 4:** Run the new tests and `tests/processing tests/api` — PASS; `ruff check` / `ruff format --check` clean.
- [ ] **Step 5:** Contract + architecture docs; Progress (tick, *Next step* = Task 2); commit `feat(engine): treat an Ollama on another PC as remote in the GPU gate and /health`.

### Task 2: Fail fast when the Ollama PC is unreachable

**Files:**
- Modify: `engine/src/vozata/ports.py` (new `LlmUnreachableError`), `engine/src/vozata/llm/ollama.py`, `engine/src/vozata/session_finisher.py` (`write_minutes`, `extract_action_items`), `engine/src/vozata/api/minutes_job.py`, `engine/src/vozata/api/action_items_job.py`, `engine/src/vozata/api/ask_job.py`, `engine/src/vozata/locales/{en,pt-BR,es}.toml`
- Test: `engine/tests/llm/test_ollama.py`, `engine/tests/test_session_finisher.py`, `engine/tests/api/test_minutes_job.py`, `engine/tests/api/test_action_items_job.py`, `engine/tests/api/test_ask_job.py` (existing files with those names, or where each class is tested today), a queue-level test (`engine/tests/processing/…`)
- Docs: `docs/roadmap/api-contract.md` (`error` code `llm_unreachable`), `docs/roadmap/architecture.md` (failure rule)

**Interfaces:**
- Consumes: `net.url_host` (Task 1).
- Produces: `class LlmUnreachableError(LanguageModelError)` in `ports.py` with attribute `host: str`; constructor `LlmUnreachableError(host: str, detail: str)`. Locale keys `errors.llm_unreachable.minutes`, `errors.llm_unreachable.action_items`, `errors.llm_unreachable.answer` (param `host`). Error event code `llm_unreachable`.

English copy (translate for pt-BR / es):
- minutes: `Could not reach Ollama at {host}. Regenerate the minutes when it is available.`
- action_items: `Could not reach Ollama at {host}. Extract the action items again when it is available.`
- answer: `Could not reach Ollama at {host}. Ask again when it is available.`

- [ ] **Step 1: Failing tests** (`httpx.MockTransport`)
  - `test_generate_raises_unreachable_when_probe_cannot_connect`: transport raises `httpx.ConnectError` on `/api/tags` → `LlmUnreachableError`, `.host == "192.168.0.20"`, and no `/api/chat` request was made. Same for `ConnectTimeout` and `ReadTimeout`; same for `stream()`.
  - `test_probe_runs_once`: two `generate()` calls → exactly one `/api/tags` request.
  - `test_probe_http_error_is_not_unreachable`: `/api/tags` → 500, `/api/chat` → 200 → `generate()` returns the content.
  - `test_chat_connect_error_is_unreachable` (Review Focus 2): probe 200, chat raises `ConnectError` → `LlmUnreachableError`.
  - `test_release_after_unreachable_sends_nothing` (Review Focus 1): after the failed probe, `release()` returns and the transport saw no `/api/chat`.
  - Finisher: a fake model raising `LlmUnreachableError("192.168.0.20", "…")` → observer error code `llm_unreachable` with the localized minutes message containing the host; `minutes` not written; action items step → `llm_unreachable` with the action-items message. Another `LanguageModelError` still gives `minutes_failed`.
  - Queue level (Review Focus 3): two queued meetings, LLM unreachable → first ends `done` with `has_minutes: false`, the second is processed.
  - `MinutesJob` / `ActionItemsJob`: `error` event code `llm_unreachable`, message from the locale. `AskJob`: answer `error` text is the `answer` message.
  - Locale parity test passes with the three new keys.
- [ ] **Step 2:** Run them — FAIL.
- [ ] **Step 3:** Implement: `_probe()` in `OllamaLanguageModel` called at the top of `generate` / `stream` (a `_reachable: bool | None` flag); map the connect errors in `generate` / `stream`; `release()` returns early when the probe failed; class docstring no longer says "local". In the finisher and the jobs, branch on `isinstance(error, LlmUnreachableError)` before the existing `LanguageModelError` handling.
- [ ] **Step 4:** Run `tests/llm tests/api tests/processing tests/test_session_finisher.py` — PASS; ruff clean.
- [ ] **Step 5:** Contract + architecture docs; Progress; commit `feat(engine): fail fast with llm_unreachable when the Ollama PC is off`.

### Task 3: UI — remote note on the Config page, unreachable message on the meeting page

**Files:**
- Create: `ui/src/VozAta.Desktop/Services/NetworkAddress.cs`, `ui/tests/VozAta.Desktop.Tests/NetworkAddressTests.cs`
- Modify: `ui/src/VozAta.Desktop/ViewModels/SettingEditorViewModel.cs`, `ui/src/VozAta.Desktop/Views/ConfigPage.axaml` (under the editor's `Help` caption, ~line 395), `ui/src/VozAta.Desktop/ViewModels/SessionPageViewModel.cs` (`OnError`), `HistoryViewModel.OnError`, `MainViewModel` (`case ErrorEvent` passes the code), `Resources/Strings{,.pt-BR,.es}.resx`
- Test: `ui/tests/VozAta.Desktop.Tests/SettingsViewModelTests.cs` (or the editor's test file), `SessionPageViewModelTests.cs`, `MainViewModelTests.cs`

**Interfaces:**
- Produces: `static class NetworkAddress { static bool IsLocalUrl(string? url); static string Host(string url); }` — same rules and table as Task 1. `SettingEditorViewModel.Note : string?` (observable, null when no note). `SessionPageViewModel.OnError(string? sessionId, string code, string message)` (and `HistoryViewModel.OnError` with the same parameters).
- Resource key `RemoteOllamaNote` = `Transcripts are sent to {0} to write the minutes.` (pt-BR / es translated).

- [ ] **Step 1: Failing tests**
  - `NetworkAddressTests` with the Task 1 table rows.
  - Editor: key `OLLAMA_URL`, `TextValue = "http://192.168.0.20:11434"` → `Note == "Transcripts are sent to 192.168.0.20 to write the minutes."`; `"http://localhost:11434"` → `Note is null`; other keys never get a note; switching language refreshes the note.
  - Meeting page: `OnError(Id, "llm_unreachable", msg)` while not busy → `Error == msg`; `OnError(Id, "minutes_failed", msg)` while not busy → `Error` unchanged (today's rule); another session's id → unchanged.
  - Resource parity test passes.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement (`Uri` + `IPAddress.IsLoopback`; `Note` updated in `OnTextValueChanged` and `RefreshTexts`); `TextBlock` bound to `Note`, `Classes="caption"`, visible when not null.
- [ ] **Step 4:** `dotnet test` (whole UI suite) — PASS; `dotnet format --verify-no-changes` clean.
- [ ] **Step 5:** Progress; commit `feat(ui): show where transcripts go for a remote Ollama and its unreachable message`.

### Task 4: Guide, full suites, manual check, phase done

**Files:**
- Create: `docs/remote-ollama.md` (the guide content listed in the spec's design notes, Windows steps, the security note)
- Modify: `docs/INSTALL.md` (link next to the Ollama row and in troubleshooting), `docs/roadmap/phases/43-remote-ollama.md`, `docs/roadmap/README.md`

- [ ] **Step 1:** Write the guide and link it.
- [ ] **Step 2:** Engine suite with coverage (output to a file; it must exit on its own), ruff; UI suite, `dotnet format`.
- [ ] **Step 3: Manual check** (scratch `DATABASE_PATH` / `OUTPUT_DIR`, through the engine API). There is no second PC: this PC's LAN address counts as remote, and the local Ollama listens on 127.0.0.1 only, so `OLLAMA_URL=http://<LAN IP>:11434` is an **off remote PC**; a small TCP forwarder in the scratchpad (`<LAN IP>:11434 → 127.0.0.1:11434`) makes it a **working remote PC**. Check: `/health` `llm.remote: true`; with the forwarder, `POST /sessions/{id}/minutes` on an imported or existing scratch meeting writes minutes and Ask answers; without it, the minutes fail in ≤ 5 s with the localized message and the queue goes on; the Config page shows the note (capture the app window with `PrintWindow`). The "live recording does not interrupt remote minutes" check needs the mic: run it only if the JBL opens (quick 5 s check first; if WASAPI is stuck, ask the user, never restart the service) — otherwise rely on the gate tests and say so.
- [ ] **Step 4:** Tick the acceptance criteria, README `done`, Progress `ready for PR`; commit `docs(roadmap): finish phase 43`; push once; open the PR; the user merges.
