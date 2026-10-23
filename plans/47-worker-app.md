# Phase 47 — Worker App and Automatic Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the GPU PC the user opens **VozAta Worker.exe** (no command line); on this PC the Config page finds the worker on the LAN and pairs with a 6-digit code; a worker whose address changed is found again before the phase 44 fallback.

**Architecture:** The worker (engine package) gains an identity (`WORKER_ID`, `WORKER_NAME`), a UDP discovery responder, rotating pairing codes with `POST /pair` and a loopback-only `GET /local/status`. The engine gains a discovery client, `GET /worker/discover`, `POST /worker/pair` (saves the keys through `SettingsFile`) and a relocation step in `build_transcriber`. The desktop Config page's Worker group gets "Find workers" + pairing. A new Avalonia project `VozAta.Worker` starts `vozata-engine.exe worker`, shows `/local/status`, and handles autostart, firewall and tray.

**Tech Stack:** Python 3.13 (FastAPI, httpx, socket), C# .NET 10 / Avalonia 12 (CommunityToolkit.Mvvm, xUnit).

**Spec:** `docs/roadmap/phases/47-worker-app.md`.

## Rulings

- **Identity**: `WORKER_ID` (uuid4 hex, generated once and appended to the worker `.env`, like the token), `WORKER_NAME` (default: `socket.gethostname()`), `WORKER_DISCOVERY_PORT` (8767). On this PC `WORKER_ID` names the paired worker (saved by pairing).
- **Discovery (UDP)**: request bytes `{"vozata":"discover","v":1}` broadcast to `255.255.255.255:<port>` and to each IPv4 interface's directed broadcast; the worker replies to the sender with `{"vozata":"worker","v":1,"id","name","port","version","gpu"}`. Anything else is ignored. The client collects replies for 1.5 s, dedupes by id, and builds `url = http://<sender ip>:<port>`. Socket I/O behind small seams (`DatagramSocket` protocol) so tests use fakes.
- **Pairing**: `PairingCodes(clock, rng)`: a 6-digit code valid 5 minutes (a new one after expiry or after a successful pairing); `check(code)` constant-time; 5 wrong codes lock for 60 s (`423 worker_pairing_locked`); wrong code `403 worker_pairing_refused`. `POST /pair {code}` → `{token, id, name}`. A worker on loopback without a token has nothing to pair (`409 worker_no_token`).
- **Open routes**: `/pair` (code instead of token) and `/local/status` (only `127.0.0.1` / `::1` clients, else `403`). `/health` and `/transcribe` keep the token guard.
- **`/local/status`**: `{version, id, name, port, addresses: [ipv4…], token, pairing_code, code_expires_in, gpu, models}` for the worker app (the token is shown on the worker PC only).
- **Engine**: `GET /worker/discover` → `{workers: [{id, name, url, version, gpu}]}`; `POST /worker/pair {url, code}` → calls the worker's `/pair`, saves `WORKER_URL`, `WORKER_TOKEN`, `WORKER_ID` through `SettingsFile.update` → `{id, name, url}`; errors `worker_pairing_refused` / `worker_pairing_locked` (409) / `worker_unreachable` (502).
- **Relocation**: `build_transcriber(..., relocate=None)`; on `WorkerUnreachableError` with `WORKER_ID` set, `relocate(settings)` discovers once; the same id at another URL → new client with that URL, probe, `on_moved(url)` saves `WORKER_URL`; else the phase 44 fallback. Wired in the API container (live sessions and queue steps).
- **Worker app** (`ui/src/VozAta.Worker`): same layout as the desktop (`engine\vozata-engine.exe` next to the exe; dev: `.venv` python `-m vozata worker`), working directory `%APPDATA%\VozAta\worker` (its own `.env`). Reuses the desktop's `IProcessRunner` / `SystemProcessRunner` / `PathResolver` by linking the files. Polls `/local/status` every 2 s. "Start with Windows" = HKCU `Software\Microsoft\Windows\CurrentVersion\Run` value `VozAta Worker` (behind `IStartupRegistry`). "Allow on the network" runs `netsh advfirewall firewall add rule` for TCP port and UDP discovery port, Private profile, elevated (`Verb=runas`) behind `IElevatedRunner`. Closing hides to the tray; Exit stops the worker. Own RESX (`WorkerStrings*.resx`) en / pt-BR / es; language = Windows UI culture.
- **Packaging**: `VozAta.Worker` published into the same folder as the desktop app (they share `engine\`), installer shortcut "VozAta Worker".

## Tasks

### Task 1: Worker identity, pairing codes, `/pair`, `/local/status`
Files: `config.py`, `settings_fields.py` (worker group: `WORKER_ID`, `WORKER_NAME`, `WORKER_DISCOVERY_PORT`), `worker/pairing.py`, `worker/app.py` (routers), `worker/local.py` (`lan_addresses`), `cli/worker.py` (id generated like the token), locales, `.env.example`; tests.
- [ ] Commit `feat(worker): pair with a rotating code and report the local status`.

### Task 2: UDP discovery (worker responder, engine client, routes)
Files: `worker/discovery.py` (responder thread, started by the worker app lifespan), `worker_client/discovery.py` (`discover_workers`), `api/routes/worker.py` (`/worker/discover`, `/worker/pair`), `worker_client/pairing.py`, container + bootstrap wiring, locales; tests with fake sockets / `MockTransport`.
- [ ] Commit `feat: find VozAta workers on the network and pair with them`.

### Task 3: Find the worker again after an address change
Files: `bootstrap.py` (`build_transcriber(relocate=…)`, API container `worker_moved`), `bootstrap_processing.py`; tests.
- [ ] Commit `feat(engine): find a moved worker before falling back`.

### Task 4: Desktop Config — Find workers and pair
Files: `VozAta.Client` (`DiscoverWorkersAsync`, `PairWorkerAsync`, DTOs), `WorkerPairingViewModel`, `ConfigPage.axaml` (worker group block), RESX; tests (`FakeEngineClient`, view model, client).
- [ ] Commit `feat(ui): find and pair a worker from the Config page`.

### Task 5: The worker app
Files: `ui/src/VozAta.Worker/` (csproj, Program, App, `WorkerWindow`, `WorkerAppViewModel`, services: `WorkerStatusClient`, `RegistryStartup`, `ElevatedRunner`, `WorkerOptions`), `VozAta.sln`, tests project reference + `WorkerAppViewModelTests`, resource parity.
- [ ] Commit `feat(worker-app): run the worker from a window on the GPU PC`.

### Task 6: Packaging and docs
Files: `packaging/build.ps1` (publish `VozAta.Worker` to the UI output), `packaging/installer.iss` (shortcut), `docs/remote-worker.md` (around the app), `docs/roadmap/worker-api.md`, `api-contract.md`, `architecture.md` §9.
- [ ] Commit `docs: the worker app, discovery and pairing`.

### Task 7: Full suites, manual check, phase done
- [ ] Engine `pytest --cov`, ruff; UI `dotnet test`, `dotnet format --verify-no-changes`.
- [ ] Manual: run the worker app (dev) on this PC; Config → Find workers lists it; pairing with the shown code fills URL + token; Test ok; change `WORKER_PORT` → the next transcriber build relocates.
- [ ] Phase done, push, PR; the user merges.
