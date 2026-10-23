# Phase 58 — GPU support (CUDA) downloaded on the PC

## Goal

The installers no longer carry the NVIDIA cuBLAS / cuDNN libraries (1.8 GB of the 2.4 GB
installed, most of the ~1 GB installer). Whoever installs chooses: the setup offers **Download GPU
support** (shown, and ticked, when the PC has an NVIDIA driver); without it the engine
transcribes on the CPU. The download can also be run later (`vozata-engine cuda install`, or the
setup again).

## Depends on

13, 56, 57

## Read first

- `transcription/cuda.py`, `transcription/faster_whisper.py`
- `packaging/engine.spec`, `packaging/build.ps1`, `packaging/speakers.iss`

## Scope

- **CUDA runtime**: `%LOCALAPPDATA%\VozAta\cuda` (`Settings.cuda_runtime_dir`), with the same
  `nvidia/<lib>/bin` layout as the pip wheels. `transcription/cuda_runtime.py` downloads the
  pinned wheels (`nvidia-cublas-cu12` 12.9.2.10, `nvidia-cudnn-cu12` 9.27.0.42, ~1.2 GB) from
  PyPI, checks their SHA-256 against PyPI's, extracts only the DLLs and writes `ready.json`.
- `register_cuda_dlls` also registers the runtime folder. `WHISPER_DEVICE=auto` in the packaged
  engine without any CUDA folder goes straight to the CPU model (no GPU model download first).
- `vozata-engine cuda install | status [--json] | remove`, with download progress lines.
- **Build**: never bundles CUDA (the `CPU_ONLY` switch and `-CpuOnly` go).
- **Installers** (`packaging/gpu.iss`, included by both): the task, only on a PC with
  `nvidia-smi.exe`, ticked; runs `cuda install` in a console; uninstall removes the runtime
  unless the other product is still installed (like `speakers.iss`).

## Acceptance criteria

- [ ] The installers are under ~450 MB and hold no `nvidia` folder.
- [ ] `vozata-engine.exe cuda install` on the reference machine downloads and extracts the DLLs;
      the packaged engine then transcribes on the GPU.
- [ ] Without the runtime the packaged engine transcribes on the CPU without downloading the GPU
      model.

## Tests

Wheel lookup (the win_amd64 file and its digest), download with progress and digest check (a bad
digest leaves nothing), extraction of only the DLLs, readiness, removal; the DLL folder
registration with the runtime; the CPU shortcut of `auto`; the CLI.

## Out of scope

A Download GPU support button in the apps (the setup and the command cover it), other CUDA
versions.

## Kickoff prompt

> Start phase 58 (`docs/roadmap/phases/58-cuda-on-demand.md`): read its *Read first* files,
> write `plans/58-cuda-on-demand.md`, then implement it task by task.

## Progress

- **Branch:** `feature/58-cuda-on-demand`
- **Status:** in progress
- **Updated:** 2026-10-23 18:40
- **Next step:** `cli/cuda.py` (install | status | remove) + locales + `__main__`.

### Steps

- [x] Phase start
- [x] Engine: CUDA runtime download, DLL registration, the CPU shortcut
- [ ] CLI `cuda install | status | remove`
- [ ] Packaging: no CUDA in the build; `gpu.iss` in both installers
- [ ] Docs; suites; build; GPU check with the downloaded runtime; copy to F:
