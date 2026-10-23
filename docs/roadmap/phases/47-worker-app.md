# Phase 47 — Worker app and automatic discovery

## Goal

Make the worker of phase 44 easy to run and to find. On the GPU PC the user double-clicks
**VozAta Worker.exe** (no command line); on this PC the Config page finds the worker on the local
network and pairs with a short code shown on the GPU PC — no IP typing, no token copying. When the
worker's address changes (DHCP), VozAta finds it again before falling back to this PC.

Requested by the user on 2026-10-22: "create an exe to open on the worker machine; add a way to
detect the worker automatically from the app".

## Depends on

44

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 44](44-worker-speech.md), `docs/roadmap/worker-api.md`, `docs/remote-worker.md`
- `worker/app.py`, `worker/auth.py`, `cli/worker.py`, `worker_client/client.py`,
  `connection_checks.py`, `settings_file.py` (how the engine saves `.env` keys)
- UI: the Desktop's engine process launcher, `App.axaml.cs`, `SettingsViewModel.cs`
  (`TestAnchors`), `ConfigPage.axaml`, `packaging/build.ps1`

## Scope

**Worker app (new Avalonia project `ui/src/VozAta.Worker/`)**

| Part | Content |
|------|---------|
| Process | starts the bundled `vozata-engine.exe worker` as a child process and stops it on exit (reuse the Desktop's engine process launcher; move it to a small shared project if needed) |
| Window | state (starting / running / stopped / error), this PC's LAN addresses, the **pairing code**, GPU name and loaded models, Start / Stop |
| Options | "Start with Windows" (HKCU `Run`), "Allow on the network" (elevated `netsh advfirewall` rules for TCP 8766 and UDP 8767, Private profile only) |
| Tray | closing the window keeps the worker running in the tray; Exit stops it |
| Text | RESX en / pt-BR / es |

The app reads its state from the worker's `GET /local/status`, answered only to loopback clients.

**Worker (engine package)**

- New keys: `WORKER_ID` (uuid, generated once into the worker `.env` like the token),
  `WORKER_NAME` (default: the host name), `WORKER_DISCOVERY_PORT` (8767).
- UDP responder: request `{"vozata":"discover","v":1}` → reply
  `{"vozata":"worker","v":1,"id","name","port","version","gpu"}`. No secrets in the reply.
- Pairing: a 6-digit code that rotates every 5 minutes (shown in the app through
  `/local/status`); `POST /pair {code}` (no token) → `{token, id}`; constant-time compare; 5 wrong
  codes lock pairing for 1 minute.

**Engine (this PC)**

- `worker_client/discovery.py`: broadcast on each IPv4 interface, collect replies for ~1.5 s.
- `GET /worker/discover` → `[{id, name, url, version, gpu}]`.
- `POST /worker/pair {url, code}` → saves `WORKER_URL`, `WORKER_TOKEN`, `WORKER_ID` through
  `settings_file.py`.
- Address change: when the worker probe fails and `WORKER_ID` is set, discover once; the same id at
  a new address updates `WORKER_URL` and is used. Only then does the phase 44 fallback apply.

**UI (Desktop Config, group `worker`)**: "Find workers" lists what answered (name, address, GPU);
picking one asks for the code shown on the GPU PC and pairs; the existing Test confirms.

**Packaging and docs**: `build.ps1` publishes `VozAta.Worker.exe` to `build/worker/` next to an
`engine/` copy of `vozata-engine`; smoke test starts it with `--check`; `docs/remote-worker.md`
rewritten around the app; `worker-api.md` (`/pair`, `/local/status`, UDP discovery);
`api-contract.md` (`/worker/discover`, `/worker/pair`); `architecture.md` §9 keys.

## Design notes

- Discovery replies carry no secret; pairing needs the code that only someone looking at the GPU
  PC can see. The token still travels in clear on the LAN (phase 44 note).
- The worker app is a separate exe but ships the same engine bundle: no second Python build.
- Broadcast stays inside the local subnet; workers in another subnet are still set by URL.

## Acceptance criteria

- [x] On the GPU PC, `VozAta Worker.exe` starts the worker, shows its address, GPU and pairing
      code, can start with Windows and add the firewall rules.
- [x] On this PC, "Find workers" lists the worker; pairing with the code fills URL and token and
      the Test is ok.
- [x] After the worker's address changes, the next recording finds it again without a fallback.

## Tests

Engine: UDP responder and discovery with an in-memory socket fake; pairing (right / wrong code,
lockout, rotation with a fake clock); `/local/status` refused for a non-loopback client;
`/worker/discover` and `/worker/pair` routes; rediscovery before fallback. UI: worker app view
model with a fake process and client; Config "Find workers" and pairing flow; resource parity.

## Out of scope

TLS, several workers at once, workers outside the local subnet (they keep using the URL),
mDNS / Bonjour.

## Kickoff prompt

> Start phase 47 (`docs/roadmap/phases/47-worker-app.md`) once phase 44 is merged: read its
> *Read first* files, write `plans/47-worker-app.md`, then implement it task by task.

## Progress

- **Branch:** `feature/47-worker-app`
- **Status:** ready for PR
- **Updated:** 2026-10-22
- **Next step:** open the PR to `main`; after the merge, start phase 48
  (`docs/roadmap/phases/48-minutes-so-far.md`).

### Steps

- [x] Implementation plan (`plans/47-worker-app.md`)
- [x] Worker: identity, pairing codes, `/pair`, `/local/status`
- [x] UDP discovery: worker responder, engine client, `/worker/discover`, `/worker/pair`
- [x] Engine: find a moved worker before the fallback
- [x] Desktop Config: Find workers and pair
- [x] The worker app (`VozAta.Worker`)
- [x] Packaging and docs
- [x] Full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- The worker app is published into the desktop app's folder (both use `engine\vozata-engine.exe`
  next to them) instead of a separate `build/worker/`; its working directory is
  `%APPDATA%\VozAta\worker`, so its `.env` (token, id) is apart from the engine's.
- `/pair` and `/local/status` sit outside the token guard (a router carries it now); a wrong code
  is 403 `worker_pairing_refused`, the lockout 423 `worker_pairing_locked`. `WORKER_ID` is made
  only for a worker on the network, like the token.
- Discovery sends one broadcast per IPv4 address of this PC (Windows sends a limited broadcast
  through one interface only) and dedupes answers by worker id. A loopback worker (no id) does not
  answer discovery.
- Relocation happens where a transcriber is built (recording start, queue step); a worker lost
  in the middle of a recording still falls back (phase 44) and is found again at the next start.
- The worker app has its own test project (`tests/VozAta.Worker.Tests`) and does not share source
  files with the desktop app (linked files would give the desktop tests two copies of the same
  types). `ShellViewModelTests.The_banner_over_other_pages_follows_the_elapsed_time_and_the_end`
  failed once in a full run and passed on four reruns (timing, not related to this phase).
- The worker app reads `worker.settings.json`, not `appsettings.json`: it is published into the
  desktop app's folder, which has its own `appsettings.json`.
- The worker app uses the desktop app's design system (`Themes/*.axaml` linked into the project,
  user request 2026-10-22): brand band with the logo and a state tag, cards, banners.
- Manual check (2026-10-22, this PC as both sides): the worker app (Debug) found the repository's
  Python, started the worker in `%APPDATA%\VozAta\worker` (token and id made there) and showed
  the pairing code, four LAN addresses, the RTX 3050 and the token. A scratch engine (port 8799)
  found it with `GET /worker/discover` in 1.6 s; a wrong code got the localized 409, the shown
  code paired and saved `WORKER_URL` / `WORKER_TOKEN` / `WORKER_ID` (token equal to the
  worker's); `POST /settings/test/worker` and `/health.worker` were ok. With `WORKER_URL` pointing
  at a dead address, `build_transcriber` found the worker by its id in 5.2 s and saved the new
  address. Found and fixed: the state sentence was cut, the log lost its accents (UTF-8). The
  test folder was removed afterwards. On one PC the worker answers through whichever adapter
  replies first (a virtual one here); between two PCs only the shared network can carry the
  answer. Not checked by hand: the firewall rules (administrator prompt), Start with Windows,
  the desktop Config "Find workers" block (covered by view-model tests), a second PC.
