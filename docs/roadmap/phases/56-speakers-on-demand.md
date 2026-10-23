# Phase 56 — Speaker identification downloaded on the PC

## Goal

One installer for everyone. Speaker identification (pyannote + torch, ~2.5–3 GB) is no longer
packaged into a "speakers edition": the PC that needs it downloads it itself, from the installer
(an optional task), from VozAta Worker (a button on the Tasks card) or from the command line
(`vozata-engine speakers install`). The speakers edition of phase 51 is removed: it was too big
to build (PyInstaller ran out of memory collecting torch) and to ship.

## Depends on

14, 45, 51

## Read first

- `engine/CLAUDE.md`
- `diarization/models.py` (`has_extra`), `diarization/subprocess_diarizer.py`,
  `diarization/subprocess_embedder.py` (the child processes), `frozen.py`, `worker/tasks.py`
- `packaging/engine.spec`, `packaging/build.ps1`, `packaging/installer.iss`
- `ui/src/VozAta.Worker/ViewModels/WorkerAppViewModel.cs`

## Scope

- **The speaker runtime**: a separate Python 3.13 environment in
  `%LOCALAPPDATA%\VozAta\speakers` (`Settings.speakers_runtime_dir`, from `LOCALAPPDATA`) with `torch`,
  `torchaudio` (the CUDA 12.8 wheels when an NVIDIA GPU is present, else the CPU ones),
  `torchcodec` and `pyannote.audio`. The diarizer and the live embedder already run in child
  processes (phase 14 / 15); in the packaged engine the children now start with the runtime's
  Python, with the engine's own source (`engine/speakers/vozata.zip`, built by `build.ps1`) on
  `PYTHONPATH`, so the runtime never holds a stale copy of VozAta.
- **Install**: `uv` (shipped next to the engine, `engine/speakers/uv.exe`, ~40 MB) creates the
  environment (it downloads its own Python) and installs the pinned packages; an import check
  then writes `ready.json`. Re-running is safe: a ready runtime is kept, a broken one rebuilt.
  `vozata-engine speakers install` prints one line per step; `speakers status [--json]` says
  ready / not installed; `speakers remove` deletes the folder.
- **Availability**: `diarization.models.has_extra()` is true in the packaged engine once the
  runtime is ready (in development, as before, when the venv has the `diarization` extra). The
  worker's tasks then offer speakers (with `HF_TOKEN`). The `missing_extra` reason now tells how
  to install it.
- **Installer**: an optional task "Download speaker identification (~3 GB)" runs
  `vozata-engine.exe speakers install` in a console window at the end of the setup. `build.ps1
  -Speakers`, the `SPEAKERS` spec switch and the `Edition` define are removed.
- **VozAta Worker**: when speakers are `missing_extra`, the row has a **Download** button: it runs
  the install (the last output line shows as progress), then restarts the worker.

## Design notes

- The runtime is the same for VozAta and VozAta Worker on a PC (both run
  `engine\vozata-engine.exe`).
- The pinned versions match the development environment of the reference machine
  (torch 2.11.0, torchaudio 2.11.0, torchcodec 0.17.0, pyannote.audio 4.0.7).
- `uv`'s cache goes inside the runtime folder and is deleted after a successful install.

## Acceptance criteria

- [ ] The standard build has no torch and stays ~1 GB; `build.ps1` has no `-Speakers`.
- [ ] `vozata-engine.exe speakers install` on the reference machine builds the runtime;
      `worker --check --json` then shows speakers not `missing_extra`; a diarization run of the
      packaged engine works through it.
- [ ] VozAta Worker downloads it from the Tasks card and then offers speakers.
- [ ] The installer offers the optional download.

## Tests

Runtime layout and readiness (marker, missing Python), the child command and environment
(frozen with / without the runtime, development), the install steps (CUDA vs CPU index, a
failed step stops and leaves no marker, a ready runtime is kept), the CLI output, the worker
app's Download button (progress, failure, restart).

## Out of scope

A download inside the desktop app's Config page (the installer task and the worker app cover
it), other runtimes (translation already ships in the standard build).

## Kickoff prompt

> Start phase 56 (`docs/roadmap/phases/56-speakers-on-demand.md`): read its *Read first* files,
> write `plans/56-speakers-on-demand.md`, then implement it task by task.

## Manual check (2026-10-23, reference machine)

- The real runtime, with a bundle like `build.ps1` makes (`uv.exe` 0.13.5 + `vozata.zip`):
  `install` ran the four steps (CUDA variant) into `%LOCALAPPDATA%\VozAta\speakers`;
  `ready.json` = torch 2.11.0+cu128, CUDA 12.8, pyannote 4.0.7; 4.6 GB on disk. The runtime's
  Python imports `vozata` from the zip and sees the GPU.
- `pyannote_from_settings` with that runtime diarized `benchmarks/tts-meeting/audio.wav`
  (62.9 s, one voice): 10 turns, 1 speaker, 38.8 s including the model load.
- The installer script compiles with Inno Setup 7.1 (the task and the uninstall entry).
- The packaged build itself was stopped twice by Claude Code's low-memory guard during
  PyInstaller's COLLECT step (not a build error); still to run: the full `build.ps1`, then
  `vozata-engine.exe speakers status --json` / `worker --check --json` from the build.

## Progress

- **Branch:** `feature/56-speakers-on-demand`
- **Status:** in progress
- **Updated:** 2026-10-23 16:00
- **Next step:** full suites, then the manual check: build the installer, `speakers install` from the packaged engine, a diarization run.

### Steps

- [x] Phase start (phase file, plan, README)
- [x] Engine: the speaker runtime (layout, readiness, child command and env) — `992bb80`
- [x] Engine: the installer (uv steps) and `speakers install | status | remove`
- [x] Packaging: `vozata.zip` + `uv.exe`, the edition removed, the installer task (`frozen.py` removed: the children no longer run through `vozata-engine.exe -m`)
- [x] Worker app: the Download button — `e185465`
- [x] Docs (INSTALL, remote-worker, two-pc-check, architecture, worker-api)
- [ ] Full suites; manual check (packaged build, runtime install, diarization)
