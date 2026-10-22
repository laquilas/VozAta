# Phase 43 — Ollama on another PC of the local network

## Goal

Let the minutes, action items and "Ask" run on a **better PC on the local network** that runs the
Ollama server, so this laptop's GPU only handles speech and speakers. `OLLAMA_URL` already
accepts any address; this phase makes that setup **first-class**:

- the phase 40 GPU gate treats a remote Ollama as "no local GPU": a live recording no longer
  interrupts the minutes / action-items steps, and Ask no longer waits for the queue;
- an unreachable remote server fails fast with a clear message and never blocks the queue;
- the Config page shows that transcript text is sent to another machine, and a test button;
- a short guide explains how to set up the other PC.

Requested by the user on 2026-10-20.

## Depends on

40

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 40](40-background-processing.md) (pause rule, job steps)
- [phase 25](25-llm-vram-release.md) (`release()` / `OLLAMA_KEEP_ALIVE`)
- `llm/ollama.py`, `connection_checks.py`, `settings_options.py`,
  `transcription/openai_compatible.py` (`remote_host()`), `api/routes/health.py`

## Current state (facts, 2026-10-20)

- `OllamaLanguageModel` (`llm/ollama.py`): `httpx` timeout 300 s; `is_available()` 3 s; every
  `httpx.HTTPError` → `LanguageModelError` → `minutes_failed` / `action_items_failed`. Jobs send
  `keep_alive: "5m"`, then `release()` sends `OLLAMA_KEEP_ALIVE` (default `0`) to unload.
- No localhost check exists; the class docstring says "local Ollama server";
  `settings_options.py` lists models from `/api/tags` with a 2 s timeout.
- `remote_host()` exists for the external STT (phase 12) and drives a privacy note in
  `/health` and the CLI.
- The Config page has `OLLAMA_URL`, `OLLAMA_MODEL` (list from `/api/tags`) and a connection test.

## Scope

**Engine**

| File | Content |
|------|---------|
| `net.py` (new, or move `remote_host()` there) | `is_local_url(url)`: loopback names and addresses (`localhost`, `127.0.0.0/8`, `::1`) are local; anything else, including this PC's LAN address, is remote |
| `processing/gpu_gate.py` | the LLM consumer (minutes, action items, Ask) uses the local GPU only when Ollama is local |
| `llm/ollama.py` | before a job, `is_available()`; unreachable → `LanguageModelError` with code `llm_unreachable` and the URL, in ≤ 5 s; docstring no longer says local |
| `routes/health.py` | `llm.remote: bool` (and the host) |
| `minutes` / `action_items` failure messages | `llm_unreachable` localized: "Could not reach Ollama at <host>. Regenerate the minutes when it is available." |
| `locales/*.toml` | messages |
| `docs/INSTALL.md` (or `docs/remote-ollama.md` linked from it) | guide for the other PC (below) |

**UI**

| File | Content |
|------|---------|
| Config page, minutes section | when the URL is remote: a note "Transcripts are sent to <host> to write the minutes"; the existing connection test works against it |
| Meeting page | the `llm_unreachable` message next to "Regenerate minutes" |
| Resources | strings in en / pt-BR / es |

## Design notes

- **Gate**: with a remote Ollama, a meeting's minutes can be written while the next meeting
  records live; local transcribe and diarize steps are still interrupted (phase 40).
- **`OLLAMA_KEEP_ALIVE`**: unchanged. Unloading right away (`0`) frees the remote GPU too; the user
  may prefer `5m` on a dedicated server, which the existing setting allows. The Whisper release
  before the LLM step (phase 25) is skipped when Ollama is remote, so the speech model can stay
  loaded if `WHISPER_KEEP_LOADED` asks for it.
- **Unreachable server**: the queue goes on to the next step / meeting; the meeting ends `done`
  with `has_minutes: false` and the error; "Regenerate minutes" retries later. No automatic retry
  in this phase.
- **Timeouts**: the 300 s request timeout stays (a remote LLM is faster, not slower); only the
  availability probe is new.
- **Guide content** (for the other PC, Windows): install Ollama; set the user environment variable
  `OLLAMA_HOST=0.0.0.0:11434` and restart Ollama; `ollama pull <model>`; allow inbound TCP 11434 on
  the private network profile (`New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound
  -Protocol TCP -LocalPort 11434 -Profile Private -Action Allow`); give the PC a fixed address
  (DHCP reservation); on this laptop set Config → Minutes → Ollama URL to
  `http://<address>:11434` and press Test. Security note: Ollama has no authentication; expose it
  only on a trusted private network.
- Ask the meeting (phase 24) uses the same model and benefits automatically.

## Acceptance criteria

- [ ] With `OLLAMA_URL` pointing to another PC, minutes, action items and Ask work, and `/health`
      reports `llm.remote: true`.
- [ ] While a meeting records live, a queued meeting's minutes step keeps running when Ollama is
      remote, and is interrupted when it is local.
- [ ] With the remote PC off, the minutes step fails in ≤ 5 s with the localized message, the
      meeting ends `done` without minutes, and the next queued meeting is processed.
- [ ] The Config page shows the remote note; the guide is linked from `docs/INSTALL.md`.
- [ ] Contract docs updated (`llm.remote`, `llm_unreachable`).

## Tests

Engine: `is_local_url` table (localhost, 127.x, ::1, LAN IPs, host names), gate decision with a
local vs. remote URL, unreachable fast-fail with a fake HTTP transport, health field, failure
does not block the queue. UI: remote note visibility, error message on the meeting page, locale
parity.

## Out of scope

- Running Whisper or the diarizer on the other PC (the external STT of phase 12 already covers an
  OpenAI-compatible speech server).
- Discovering Ollama servers on the network automatically.
- Authentication or TLS in front of Ollama.

## Progress

- **Branch:** `feature/43-remote-ollama`
- **Status:** in progress
- **Updated:** 2026-10-22
- **Next step:** Task 2 of `plans/43-remote-ollama.md` (fail fast with `llm_unreachable`).

### Steps

- [x] Implementation plan (`plans/43-remote-ollama.md`)
- [x] Local or remote: helper, GPU gate, Whisper release, `/health`
- [ ] Fail fast when the Ollama PC is unreachable (`llm_unreachable`)
- [ ] UI: remote note on the Config page, unreachable message on the meeting page
- [x] Guide written (`docs/remote-ollama.md`, linked from `docs/INSTALL.md`)
- [x] UI: reload the model list when the Ollama URL is saved or tested
- [ ] Full suites, manual check on a real second PC

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20: save GitHub Actions minutes).
- The rulings at the top of the plan settle what the spec leaves open: loopback-only "local"
  (empty and `0.0.0.0` count as local), one probe per model object, no `release()` after an
  unreachable probe, error code `llm_unreachable`, `/health` `llm.host`, the Config note computed
  in the UI.
- The guide is written early (`docs/remote-ollama.md`, linked from `docs/INSTALL.md`). It also says
  why the engine cannot run on another PC (it captures the local audio and has no authentication);
  the last step still has to check it against the finished phase and a real second PC.
- Found while testing: the Config page loads the `OLLAMA_MODEL` list once, at startup, so a new
  `OLLAMA_URL` keeps the old list until the app restarts. Fixed in this phase: saving the URL and the Ollama Test button read the list again.
- Related, not in this phase: issue #58 (skip the GPU Whisper download on `auto` without CUDA).
