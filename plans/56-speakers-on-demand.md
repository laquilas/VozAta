# Plan — Phase 56: speaker identification downloaded on the PC

Phase file: `docs/roadmap/phases/56-speakers-on-demand.md`. Branch `feature/56-speakers-on-demand`.

## Engine

- `diarization/runtime.py`: `SpeakerRuntime(root, source_zip, frozen)` with `python`, `marker`,
  `is_ready()`, `child(module) -> (command, env) | None`; `default_runtime()` reads
  `SPEAKERS_RUNTIME_DIR` / `%LOCALAPPDATA%`. Development (not frozen): `sys.executable`, env None.
- `diarization/models.has_extra()`: frozen → the runtime is ready.
- `subprocess_diarizer` / `subprocess_embedder`: an `env` parameter; the `*_from_settings` take
  the command from the runtime.
- `diarization/runtime_install.py`: `install(runtime, uv, gpu, run, say)`: venv (Python 3.13),
  torch + torchaudio (cu128 or cpu index), pyannote.audio + torchcodec, import check, marker,
  cache removed. `run(argv, env) -> int` injected.
- `cli/speakers.py`: `install | status [--json] | remove`, locale lines in en / pt-BR / es.

## Packaging

- `build.ps1`: `uv.exe` (from the venv, `uv` added to the `package` extra) and `vozata.zip`
  (`packaging/make_source_zip.py`) into `dist/vozata-engine/speakers/`; `-Speakers` removed.
- `engine.spec`: SPEAKERS removed, the speaker packages always excluded.
- `installer.iss`: `Edition` removed; task `speakers` (unchecked) → `[Run]` the install.
- `release.yml`: no speakers job.

## Worker app

- `ISpeakerInstaller` (runs `engine speakers install`, reports lines, returns success).
- `WorkerTaskRow.CanDownload`; `DownloadSpeakersCommand`: progress text, error, then
  Stop + Start.
