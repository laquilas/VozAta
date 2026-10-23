# Phase 46 — Worker Translation and One-Switch Setup Implementation Plan

**Goal:** Live translation can run on the VozAta worker (fallback: local opus-mt with a notice); the Config page's Worker section chooses per task whether speech, speakers and translation use the worker; the sidebar shows where the work runs.

**Spec:** `docs/roadmap/phases/46-worker-translation.md`.

## Rulings

- Worker: `TranslateService` (opus-mt loaded on the first request, kept, locked), `POST /translate {text, source, target}` → `{text}`; 503 `worker_translation_unavailable` without the `translation` extra there (`opus_mt.has_extra()`), 422 `worker_translation_failed`; capabilities add `translation`.
- Engine: `WorkerClient.translate`, `WorkerTranslator` (unreachable → local opus-mt once with the `translation` notice; worker error → `TranslationError`, which the translation worker already reports), `TRANSLATORS["vozata_worker"]`, notices passed to the session's translator factory.
- `/health`: `worker.tasks = {speech, speakers, translation}` → `worker` | `local` | `fallback` (worker chosen but not answering). Speech uses the start-up settings, the others the current file.
- UI: `WorkerTasksViewModel` in the Worker group: three toggles that set the `STT_PROVIDER` / `DIARIZATION_PROVIDER` / `TRANSLATION_PROVIDER` editors to `vozata_worker` or the local provider (saved with the page's Save); the sidebar status adds a worker line from `/health` (`Worker` / `This PC (worker off)`), refreshed on `worker_fallback`.

## Tasks

- [x] Task 1: engine (worker route, client, translator, registry, health tasks) with tests; commit.
- [ ] Task 2: UI (DTO, toggles, sidebar line, resources) with tests; commit.
- [ ] Task 3: docs, suites, manual check, PR, merge.
