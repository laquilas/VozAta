# Plan — Phase 51: the installed worker ships every task

Phase file: `docs/roadmap/phases/51-worker-every-task.md`. Branch `feature/51-worker-every-task`.

## Tasks

1. **Worker tasks (engine).** `diarization/models.py` gets `has_extra()` (`find_spec` of `torch`
   and `pyannote.audio`, no import). New `worker/tasks.py`: frozen `WorkerTask(name, available,
   reason)`, `worker_tasks(hf_token, translation_extra=, diarization_extra=)` → speech always;
   speakers needs extra (`missing_extra`) then token (`missing_hf_token`); translation needs its
   extra. `build_worker_app` builds the speakers / translation services from that list (fixes
   "HF_TOKEN alone offers speakers"). `create_worker_app(tasks=...)`: `/local/status` adds
   `tasks`. Tests first: every combination, `/local/status.tasks`, bootstrap capabilities with
   token but no extra.
2. **`worker --check` lists the tasks.** `run_worker(..., tasks=...)` prints one localized line
   per task (`cli.worker_task_offered` / `cli.worker_task_missing_extra` /
   `cli.worker_task_missing_hf_token`, task names `cli.worker_task.<name>`), en / pt-BR / es.
3. **Frozen child processes.** `vozata/frozen.py`: `run_module_args(argv, run_module=runpy...)`
   → True after running `-m <module> [args]` as `__main__` with `sys.argv` set; False otherwise.
   `packaging/engine_main.py` calls it before `main()`.
4. **Packaging.** `engine.spec`: sentencepiece always; `SPEAKERS=1` collects torch, torchaudio,
   pyannote, lightning, asteroid / speechbrain if present, with data files and submodules.
   `build.ps1 -Speakers`. `worker --check --json` prints `{version, url, tasks}` (the human lines
   stay for a person); the smoke test parses it and asserts translation available and, with
   `-Speakers`, speakers not `missing_extra`. `installer.iss` takes an edition suffix define.
5. **Worker app Tasks card.** `WorkerStatusClient` parses `tasks`; view model exposes rows
   (name, offered, reason text with the worker `.env` path); `WorkerWindow.axaml` card; resx
   en / pt-BR / es. Tests with the fake client.
6. **Docs.** `remote-worker.md`, `worker-api.md`, `architecture.md`, phase 13 note.
7. **Checks.** Full engine and UI suites; manual: worker on port 8777 from `.venv` with
   sentencepiece installed (real translation through `/translate`), `--check --json`, a CPU-only
   PyInstaller build in the scratchpad checking `worker --check` and `-m` dispatch; the worker app
   showing the Tasks card.
