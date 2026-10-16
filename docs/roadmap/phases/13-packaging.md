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

- [ ] Installer builds in CI from a tag.
- [ ] Install on a Windows user profile without Python/.NET: app starts, engine auto-starts, a
      session records, transcribes on GPU (CPU fallback when no NVIDIA GPU), minutes generated with
      Ollama installed.
- [ ] Uninstall removes binaries and keeps recordings.

## Tests

`IEngineProcess` executable-mode unit tests; CI smoke step runs `vozata-engine.exe --version`.

## Out of scope

Auto-update, code signing (backlog), macOS/Linux packages.

## Kickoff prompt

> Execute phase 13 of the roadmap (`docs/roadmap/phases/13-packaging.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/13-packaging`
- **Status:** in progress
- **Updated:** 2026-10-17 01:15
- **Next step:** engine: `register_cuda_dlls` also searches the PyInstaller bundle (`sys._MEIPASS`); `packaging/engine.spec` + `packaging/engine_main.py`; `package` extra with pyinstaller; build locally and run `vozata-engine.exe --version` and a GPU transcription smoke

### Steps

- [x] Start the phase (README status, Progress section)
- [x] UI: executable mode in `EngineProcess` + installed `appsettings` — this commit
- [ ] Engine: frozen-build CUDA DLL lookup, `packaging/engine.spec`, entry script, local build + GPU smoke
- [ ] Installer: `packaging/installer.iss`, first-run `.env` from `.env.example`, `docs/INSTALL.md`
- [ ] `.github/workflows/release.yml` (tags `v*` + manual run), CI smoke `vozata-engine.exe --version`
- [ ] Manual: CI installer → silent per-user install, app + engine start, uninstall keeps recordings

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
