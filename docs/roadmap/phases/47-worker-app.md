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

- [ ] On the GPU PC, `VozAta Worker.exe` starts the worker, shows its address, GPU and pairing
      code, can start with Windows and add the firewall rules.
- [ ] On this PC, "Find workers" lists the worker; pairing with the code fills URL and token and
      the Test is ok.
- [ ] After the worker's address changes, the next recording finds it again without a fallback.

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
