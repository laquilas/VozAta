# Phase 46 — Worker on another PC: translation and one-switch setup

## Goal

Finish the move of the heavy work to the worker: live translation runs there too, and the Config
page offers one place to set the worker up and choose, per task, whether speech, speakers and
translation use it. The user sees at a glance whether the worker is in use or VozAta fell back to
this PC.

## Depends on

44 (45 for the speakers toggle)

## Read first

- [phase 44](44-worker-speech.md), [phase 45](45-worker-speakers.md), `docs/roadmap/worker-api.md`
- [phase 29](29-live-translation.md), `ports.py` (`Translator`), `translation/opus_mt.py`,
  `translation/worker.py`, `ui/.../ConfigPageViewModel.cs`, `ui/.../ShellViewModel.cs` and
  `HealthViewModel.cs` (the sidebar's engine status)

## Scope

**Worker**: `POST /translate` `{text, source, target}` → `{text}` with the opus-mt models on the
worker; capabilities add `"translation"`.

**Engine**: `TRANSLATORS["vozata_worker"]`; fallback to `opus_mt` with the notice; `/health` lists
where each task runs now (`worker` | `local` | `fallback`).

**UI**: a **Worker** section on the Config page: URL, token, Test, and three toggles ("use the worker
for speech / speakers / translation") that set `STT_PROVIDER`, `DIARIZATION_PROVIDER`,
`TRANSLATION_PROVIDER`; the sidebar status shows "Worker" or "This PC (worker off)".

**Docs**: `docs/remote-worker.md` finished (all tasks, VRAM table for the GPU PC with Ollama).

## Acceptance criteria

- [x] Live translation runs on the worker; worker off → local opus-mt and a notification.
- [x] The Worker section sets everything up without editing `.env`; the sidebar shows where the work
      runs.

## Tests

Translator contract (local and worker), toggles map to the provider keys, sidebar status, resource
parity.

## Out of scope

Several workers, load balancing, TLS.

## Kickoff prompt

> Start phase 46 (`docs/roadmap/phases/46-worker-translation.md`) once phase 45 is merged: read its
> *Read first* files, write `plans/46-worker-translation.md`, then implement it task by task.

## Progress

- **Branch:** `feature/46-worker-translation`
- **Status:** ready for PR
- **Updated:** 2026-10-22
- **Next step:** open the PR to `main`. Phase 46 is the last planned phase.

### Steps

- [x] Implementation plan (`plans/46-worker-translation.md`)
- [x] Engine: `/translate` on the worker, `TRANSLATORS["vozata_worker"]` with fallback, `/health` tasks
- [x] UI: Worker toggles per task, sidebar worker status
- [x] Docs, full suites, manual check, phase done

### Decisions and notes

- The Worker section reuses the generated Worker settings group (URL, token, Test, pairing from
  phase 47) and adds the per-task toggles; they edit the provider keys and are saved with Save.
- A worker that answers but does not offer a task (`503 worker_*_unavailable`) is treated like one
  that does not answer: this PC runs the task with the `worker_fallback` notice (speakers too).
- Manual check (2026-10-22): `vozata worker` on `127.0.0.1:8777` from this PC's environment, which
  has no `translation` extra, listed `["speech", "speakers"]`. The engine's `WorkerTranslator`
  got `503 worker_translation_unavailable`, sent one `translation` fallback notice and translated
  the next lines locally. Not checked by hand: a real opus-mt translation on a worker (opus-mt
  itself is phase 29's), and the Config switches and sidebar line in the running app (covered by
  view-model tests).

