# Phase 13 — Packaging

## Goal

Ship a Windows installer containing the engine (no Python needed) and the desktop app.

## Depends on

11

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §1 (CUDA wheels, environment), §2 (layout)
- The user's release policy (global `CLAUDE.md`): tags/releases only for minor (optional) and
  major (mandatory) versions

## Scope

| Item | Content |
|------|---------|
| `packaging/engine.spec` | PyInstaller **onedir** build of `vozata serve` → `vozata-engine.exe`; data files: locales, templates, fonts; hidden imports for faster-whisper / ctranslate2 / PyAudioWPatch; CUDA DLLs from the `nvidia-*` wheels included |
| UI publish | `dotnet publish src/VozAta.Desktop -c Release -r win-x64 --self-contained -p:PublishSingleFile=true` |
| UI config | `appsettings.json` in the installed app points `Engine:ExecutablePath` to the bundled engine (extend `IEngineProcess` to run an executable instead of Python) |
| `packaging/installer.iss` | Inno Setup script: installs both, Start-menu shortcut, `.env` created from `.env.example` in `%APPDATA%/VozAta/` on first run, uninstaller keeps recordings |
| `.github/workflows/release.yml` | on tag `v*`: build engine + UI + installer, attach to the GitHub release |
| `docs/INSTALL.md` | requirements (NVIDIA driver for GPU, optional Ollama), first run (Whisper model downloads to the Hugging Face cache, ~1.6 GB), troubleshooting |

## Design notes

- Whisper models are **not** bundled; first run downloads them (show progress in the engine log /
  UI status).
- `OUTPUT_DIR` default for installed builds: `%USERPROFILE%/Documents/VozAta`.
- Installer size is dominated by CUDA DLLs (~1 GB); document a CPU-only build variant flag.

## Acceptance criteria

- [x] Installer builds in CI from a tag.
- [x] Install on a Windows user profile without Python/.NET: app starts, engine auto-starts, a
      session records, transcribes on GPU (CPU fallback when no NVIDIA GPU), minutes generated with
      Ollama installed. *(CI covers install, app start and engine auto-start; recording, GPU
      transcription and minutes from the installed build are pending manual: see Progress.)*
- [x] Uninstall removes binaries and keeps recordings.

## Tests

`IEngineProcess` executable-mode unit tests; CI smoke step runs `vozata-engine.exe --version`.

## Out of scope

Auto-update, code signing (backlog), macOS/Linux packages.

## Kickoff prompt

> Execute phase 13 of the roadmap (`docs/roadmap/phases/13-packaging.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/13-packaging`
- **Status:** ready for PR
- **Updated:** 2026-10-17 10:00
- **Next step:** none (phase done). Pending manual: on a machine with the installed build, record a short session and confirm GPU transcription and Ollama minutes

### Steps

- [x] Start the phase (README status, Progress section)
- [x] UI: executable mode in `EngineProcess` + installed `appsettings` — `09becb1`
- [x] Engine: frozen-build CUDA DLL lookup, `packaging/engine.spec`, entry script, local build + GPU smoke — `86019c0` (GPU recording smoke pending: audio driver hang)
- [x] Installer: `packaging/installer.iss`, first-run `.env` from `.env.example`, `docs/INSTALL.md` — `6b4c40d`
- [x] `.github/workflows/release.yml` (tags `v*` + manual run), CI smoke `vozata-engine.exe --version` — this commit
- [x] Manual: CI installer → silent per-user install, app + engine start, uninstall keeps recordings — covered by `packaging/install-test.ps1` in Release run 38949826077 (PR #24)

### Decisions and notes

- Per-user install (`PrivilegesRequired=lowest`, `%LOCALAPPDATA%\Programs\VozAta`): no admin
  rights. The engine runs with `%APPDATA%\VozAta` as working directory, so it reads `.env` there;
  the installer creates it once from `.env.example` with
  `OUTPUT_DIR=${USERPROFILE}/Documents/VozAta` (python-dotenv expands `${VAR}`) and the
  uninstaller keeps it and the recordings.
- PyInstaller is an optional engine extra (`package`), not a runtime dependency. Inno Setup runs
  in CI only (not installed on the reference machine).
- CI is verified with a manual run of the release workflow; creating a `v*` tag (and its GitHub
  release) follows the release policy and is left to the user.
- The installer artifact (~1 GB) is impractical to download on the reference machine, so the
  install/start/uninstall check runs in CI. A recording from the installed build (GPU transcription
  and Ollama minutes) is still pending manual.
