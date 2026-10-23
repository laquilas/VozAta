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

- [ ] Live translation runs on the worker; worker off → local opus-mt and a notification.
- [ ] The Worker section sets everything up without editing `.env`; the sidebar shows where the work
      runs.

## Tests

Translator contract (local and worker), toggles map to the provider keys, sidebar status, resource
parity.

## Out of scope

Several workers, load balancing, TLS.

## Kickoff prompt

> Start phase 46 (`docs/roadmap/phases/46-worker-translation.md`) once phase 45 is merged: read its
> *Read first* files, write `plans/46-worker-translation.md`, then implement it task by task.
