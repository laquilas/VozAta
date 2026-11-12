# Phase 67 — Installer maintenance: Update, Reinstall, Remove (keep or delete the data)

## Goal

Running the setup on a PC that already has VozAta offers **Update** (a newer version) or
**Reinstall** (the same version), which replace the program and keep every meeting, recording and
setting, and **Remove**, with an unticked "Also delete my data" option and a confirmation.
Installing an older version over a newer one asks first. The uninstaller from Windows Settings
asks the same question, with "No" as the default.

Requested by the user on 2026-11-12.

## Depends on

13, 57, 58

## Read first

- [phase 13](13-packaging.md), [phase 57](57-worker-installer.md), `packaging/installer.iss`,
  `packaging/installer-worker.iss`, `packaging/speakers.iss`, `packaging/gpu.iss`,
  `packaging/install-test.ps1`, `engine/src/vozata/__main__.py`, `config.py`

## Scope

| File | Content |
|------|---------|
| `engine/src/vozata/data_paths.py`, `__main__.py` | `vozata data paths` / `vozata data erase --yes`: the database (+ `-wal`, `-shm`), `OUTPUT_DIR`, the downloaded runtimes, from `Settings` |
| `packaging/maintenance.iss` | the maintenance page (Update / Reinstall / Remove + delete-data checkbox), the downgrade question, the uninstaller's question, `/DELETEDATA` / `/KEEPDATA` |
| `packaging/installer.iss`, `installer-worker.iss`, `speakers.iss` | include it; messages in en / pt-BR / es |
| `packaging/install-test.ps1` | update, reinstall, remove-keep, remove-delete, downgrade |
| README, `docs/INSTALL.md` | the maintenance options |

## Acceptance criteria

- [ ] Update and Reinstall keep `%APPDATA%\VozAta\.env`, the database and `Documents\VozAta`.
- [ ] Remove without the option keeps the data; with it (confirmed) the data is gone.
- [ ] A silent uninstall keeps the data unless `/DELETEDATA` is given.
- [ ] Installing an older version asks first.
- [ ] Every string in en / pt-BR / es; engine coverage ≥ 80 %.

## Kickoff prompt

> Execute phase 67 of the roadmap (`docs/roadmap/phases/67-installer-maintenance.md`),
> following `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/67-installer-maintenance`
- **Status:** in progress
- **Updated:** 2026-11-12
- **Next step:** `packaging/maintenance.iss` (the maintenance page, the uninstaller's question), included by both installers.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Engine: `vozata-engine data paths | erase --yes` (`cli/data.py`)
- [ ] Installer: `maintenance.iss` (Update / Reinstall / Remove, delete-data option, downgrade question, uninstaller question, `/DELETEDATA`)
- [ ] `install-test.ps1` scenarios; README / `docs/INSTALL.md`
- [ ] Build both installers, run the scenarios, PR

### Decisions and notes

- The uninstaller runs `vozata-engine data erase --yes` in `%APPDATA%\VozAta` (where the engine
  reads its `.env`), so `DATABASE_PATH` and `OUTPUT_DIR` set by the user are honoured; then it
  removes `%APPDATA%\VozAta` itself. A folder that is not VozAta's alone (a drive root, the home
  folder, Documents, Desktop) is never deleted as a whole.
