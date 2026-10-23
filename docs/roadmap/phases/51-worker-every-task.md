# Phase 51 — The installed worker ships every task

## Goal

The `vozata-engine.exe worker` that **VozAta Worker** starts on the GPU PC offers every task it
can: speech, translation and, in the speakers edition, speaker identification. When a task is
missing, the worker app says which one and why (no `HF_TOKEN`, not in this edition), so the user
knows what to do instead of seeing a silent fallback on the other PC.

Found after phases 45–47: `packaging/engine.spec` and `build.ps1` bundle neither the
`translation` extra (sentencepiece) nor the `diarization` extra (pyannote / torch), so the
installed worker only offers `speech`.

## Depends on

45, 46, 47

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 13](13-packaging.md), [phase 47](47-worker-app.md), `docs/roadmap/worker-api.md`,
  `docs/remote-worker.md`
- `packaging/engine.spec`, `packaging/build.ps1`, `packaging/engine_main.py`,
  `packaging/installer.iss`
- `bootstrap.py` (`build_worker_app`), `worker/app.py`, `cli/worker.py`,
  `translation/opus_mt.py` (`has_extra`), `diarization/subprocess_diarizer.py`,
  `diarization/subprocess_embedder.py`
- UI: `ui/src/VozAta.Worker/` (`WorkerStatusClient.cs`, `WorkerAppViewModel.cs`,
  `WorkerWindow.axaml`, `Resources/WorkerStrings*.resx`)

## Scope

**Decision: what is bundled**

| Task | Extra | Size in the bundle | Where it ships |
|------|-------|--------------------|----------------|
| speech | (core) | already there | every build |
| translation | `translation` (sentencepiece) | a few MB | **every build** |
| speakers | `diarization` (pyannote.audio, torch CUDA) | ~2.5–3 GB | the **speakers edition**: `build.ps1 -Speakers` → `VozAta-Setup-<v>-speakers.exe` |

Download on demand was rejected: a frozen PyInstaller app cannot `pip install` into itself, an
"extras pack" would need its own versioned build matched to the bundled Python and torch ABI, and
large downloads from GitHub are slow on the reference machine (~90 KB/s). Putting torch into the
only installer would triple its size for every user, most of whom never run a worker. The
speakers edition is the same installer script with one more define, so either edition can be
installed on either PC.

**Packaged child processes**

The diarizer and the live embedder run pyannote in a child process
(`sys.executable -m vozata.diarization.child`). In the frozen build `sys.executable` is
`vozata-engine.exe`, which does not understand `-m`: speakers never worked in an installed build.
`engine_main.py` runs `-m <module>` with `runpy` when frozen (a small tested helper in the
`vozata` package, `vozata/frozen.py`), so the same command works in both.

**Engine (worker)**

- `worker/tasks.py`: `worker_tasks(settings) -> list[WorkerTask(name, available, reason)]`;
  reasons `missing_extra` (the extra is not installed) and `missing_hf_token` (speakers only).
  Speakers need **both** the `diarization` extra and `HF_TOKEN` (today `HF_TOKEN` alone turns it
  on, so a worker without pyannote offers speakers and fails each job).
- `build_worker_app` builds the speakers and translation services from that list; `/health`
  `capabilities` stays the list of available task names.
- `GET /local/status` adds `tasks: [{name, available, reason}]` (loopback only, like the rest).
- `vozata worker --check` prints one localized line per task (offered / why not) and keeps exit 0.

**Packaging**

- `engine.spec`: always collect `sentencepiece`; with `SPEAKERS=1` also collect torch,
  torchaudio, pyannote.audio, lightning and their data files (model configs).
- `build.ps1 -Speakers`: sets `SPEAKERS=1`, requires the `diarization` extra, names the installer
  with the `-speakers` suffix. The smoke test checks that `worker --check` reports `translation`
  offered and, with `-Speakers`, `speakers` installed (only `missing_hf_token` left).
- `installer.iss`: `OutputBaseFilename` takes the optional edition suffix.

**Worker app (UI)**

A **Tasks** card: Speech, Speakers, Translation, each with "Offered" or the reason in words
("Needs a Hugging Face token: add HF_TOKEN to …\worker\.env and restart" / "Not in this edition:
install the speakers edition of VozAta"). Texts in en / pt-BR / es.

**Docs**: `docs/remote-worker.md` (editions, what each task needs), `worker-api.md`
(`/local/status.tasks`), `docs/roadmap/architecture.md` (packaging editions), phase 13 notes.

## Design notes

- `/health` stays as it is for the engine of the other PC: it only needs what is offered. The
  reasons are for the person at the GPU PC, so they live in `/local/status`.
- `has_extra` checks use `importlib.util.find_spec` (no torch import at startup: it takes seconds).
- The speakers edition is built and tested locally; `release.yml` (disabled) gets the switch
  but no second job until the user re-enables Actions.

## Acceptance criteria

- [ ] A build without `-Speakers` runs `worker --check` listing speech and translation as
      offered and speakers as "not in this edition".
- [ ] The frozen engine runs `-m vozata.diarization.child` (speakers can work in an installed build).
- [ ] A worker with `HF_TOKEN` but without the `diarization` extra no longer offers speakers.
- [ ] VozAta Worker shows the three tasks and why one is missing.

## Tests

Engine: `worker_tasks` for every combination (extra / token), `/local/status.tasks`, `/health`
capabilities from the list, `--check` lines, `frozen.run_module_args` (dispatch, not frozen, no
`-m`). UI: worker app view model maps `tasks` to rows and reasons (fake client); resource parity.

## Out of scope

Downloading extras on demand; editing `HF_TOKEN` from the worker app; a CPU-only torch edition.

## Kickoff prompt

> Start phase 51 (`docs/roadmap/phases/51-worker-every-task.md`): read its *Read first* files,
> write `plans/51-worker-every-task.md`, then implement it task by task.

## Progress

- **Branch:** `feature/51-worker-every-task`
- **Status:** in progress
- **Updated:** 2026-10-23
- **Next step:** finish task 4 (packaging): check the CPU-only build in the scratchpad (`worker
  --check --json` offers translation, `-m vozata --version` runs), then commit `engine.spec` /
  `build.ps1` / `installer.iss`.

### Steps

- [x] Implementation plan (`plans/51-worker-every-task.md`)
- [x] Worker tasks: `worker_tasks`, speakers need the extra and `HF_TOKEN`, `/local/status.tasks`
- [x] `worker --check` lists the tasks (`--json` for the build)
- [x] Frozen engine runs `-m <module>` (packaged child processes)
- [ ] Packaging: translation in every build, `-Speakers` edition
- [x] Worker app: Tasks card
- [x] Docs
- [ ] Full suites, manual check, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- A worker with `HF_TOKEN` but without the `diarization` extra offered speakers and failed every
  job: speakers now need both (`worker/tasks.py`). Without an explicit task list `create_worker_app`
  reports the services present with no reason.
- The packaged engine could never run speakers: the pyannote children start `sys.executable -m ...`
  and `vozata-engine.exe` did not understand `-m`. `engine_main.py` now runs it through
  `vozata.frozen.run_module_args`.
- The worker app shows the Tasks card only when the worker sends `tasks` (an older worker: no card).
  The `.env` named in the HF_TOKEN hint is the one next to `worker.log`.
