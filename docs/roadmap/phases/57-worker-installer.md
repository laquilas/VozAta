# Phase 57 — A separate installer for VozAta Worker; version 0.2.1

## Goal

Two installers instead of one: `VozAta-Setup-<v>.exe` for the PCs that record meetings (the
desktop app and the engine) and `VozAta-Worker-Setup-<v>.exe` for the GPU PC that serves the
others (VozAta Worker and the engine, without the desktop app). The version goes to 0.2.1.

## Depends on

47, 56

## Read first

- `packaging/installer.iss`, `packaging/build.ps1`, `packaging/install-test.ps1`
- `docs/remote-worker.md`, `docs/INSTALL.md`

## Scope

- `packaging/installer-worker.iss`: its own AppId and folder (`%LOCALAPPDATA%\Programs\VozAta
  Worker`), the worker app, the engine, the "VozAta Worker" shortcut, the Start-with-Windows value
  removed on uninstall, `%APPDATA%\VozAta\worker` kept.
- `packaging/speakers.iss`, included by both: the speaker identification task (phase 56) and its
  removal on uninstall, only when the other product is not installed (both use the same
  `%LOCALAPPDATA%\VozAta\speakers`).
- `installer.iss` no longer carries VozAta Worker; an upgrade from 0.1.0 deletes the old worker
  files and shortcut.
- `build.ps1`: the apps publish into `ui/` and `worker-ui/` (cleaned first), with `-p:Version`;
  both installers are compiled. `install-test.ps1 -Worker` and the Release workflow test both.
- `vozata.__version__` = 0.2.1.

## Acceptance criteria

- [x] `build.ps1 -Version 0.2.1` makes both installers; the worker one has no `VozAta.Desktop.exe`
      and the client one no `VozAta.Worker.exe`.
- [x] `install-test.ps1 -Worker` passes on the reference machine.
- [x] `vozata-engine.exe --version` prints 0.2.1.

## Tests

The engine's version tests; the install test script (worker mode) run by hand.

## Out of scope

A combined "both" installer, a machine-wide install.

## Kickoff prompt

> Start phase 57 (`docs/roadmap/phases/57-worker-installer.md`): read its *Read first* files,
> write `plans/57-worker-installer.md`, then implement it task by task.

## Manual check (2026-10-23, reference machine)

- `build.ps1 -Version 0.2.1` (~16 min): `VozAta-Setup-0.2.1.exe` 1,054 MB (no `VozAta.Worker.exe`),
  `VozAta-Worker-Setup-0.2.1.exe` 1,050 MB (no `VozAta.Desktop.exe`); `vozata-engine.exe --version`
  0.2.1; the apps carry the product version 0.2.1. Both copied to `F:\VozAta`.
- `install-test.ps1 -Worker` passed (install, `worker --check`, uninstall removes the app, the
  shortcut and a stand-in speaker runtime; the real runtime was moved aside and restored).
- Not run here: the client install test (it starts the app and engine on 8765 next to the
  user's own) and an upgrade over 0.1.0; both are in `__pendent__`.

## Progress

- **Branch:** `feature/57-worker-installer`
- **Status:** ready for PR
- **Updated:** 2026-10-23 18:10
- **Next step:** open the PR and merge it.

### Steps

- [x] Phase start
- [x] Installers: `installer-worker.iss`, `speakers.iss`, the client without the worker; build.ps1;
      install-test.ps1 `-Worker`; Release workflow
- [x] Version 0.2.1 — `db07ba5`
- [x] Docs (INSTALL, remote-worker, two-pc-check, architecture)
- [x] Build both, install test, copy to F:
