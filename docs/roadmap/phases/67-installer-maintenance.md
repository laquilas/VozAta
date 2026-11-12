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

- [x] Update and Reinstall keep `%APPDATA%\VozAta\.env`, the database and `Documents\VozAta`.
- [x] Remove without the option keeps the data; with it (confirmed) the data is gone.
- [x] A silent uninstall keeps the data unless `/DELETEDATA` is given.
- [x] Installing an older version asks first.
- [x] Every string in en / pt-BR / es; engine coverage ≥ 80 %.

## Kickoff prompt

> Execute phase 67 of the roadmap (`docs/roadmap/phases/67-installer-maintenance.md`),
> following `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/67-installer-maintenance`
- **Status:** ready for PR
- **Updated:** 2026-11-12
- **Next step:** open the PR; then `maintenance-test.ps1` and the interactive checks in `__pendent__`.

### Steps

- [x] Start the phase (README status, Progress)
- [x] Engine: `vozata-engine data paths | erase --yes` (`cli/data.py`)
- [x] Installer: `maintenance.iss` (Update / Reinstall / Remove, delete-data option, downgrade question, uninstaller question, `/DELETEDATA`)
- [x] `maintenance-test.ps1` scenarios (a separate script: `install-test.ps1` checks one clean install); README / `docs/INSTALL.md`; version 0.4.0
- [x] Build both installers (0.4.0: 189 MB and 171 MB); the scenario run is left to the user (`__pendent__`)
- [ ] PR

### Decisions and notes

- The uninstaller runs `vozata-engine data erase --yes` in `%APPDATA%\VozAta` (where the engine
  reads its `.env`), so `DATABASE_PATH` and `OUTPUT_DIR` set by the user are honoured; then it
  removes `%APPDATA%\VozAta` itself. A folder that is not VozAta's alone (a drive root, the home
  folder, Documents, Desktop) is never deleted as a whole.
- The scenarios were not run by Claude: the permission guard refused installing and removing the
  product on the user's PC. Both scripts compile with Inno Setup 7.1, and the packaged engine's
  `data paths` / `data erase` (refuses without `--yes`) were checked.
- `maintenance.iss` starts with `[CustomMessages]`: it is included right after the `[Code]` of
  `speakers.iss`, where a `;` line is not a comment (ISCC: "'BEGIN' expected").
- Update and Reinstall empty `{app}\engine` and `{app}
ecorder` first, so no file of an older
  PyInstaller build stays next to the new one.
- `SpeakersWorkDir` and `RuntimesDir` can be set on the `iscc` command line, so a test build never
  touches this PC's `%APPDATA%\VozAta` or `%LOCALAPPDATA%\VozAta` (`maintenance-test.ps1`).
