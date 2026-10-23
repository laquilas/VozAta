# Phase 45 — Worker Speakers Implementation Plan

**Goal:** With `DIARIZATION_PROVIDER=vozata_worker`, speaker identification (post-session diarization and the live embedder) runs on the VozAta worker; when it does not answer, the local pyannote runs and `worker_fallback` (task `speakers`) says so.

**Spec:** `docs/roadmap/phases/45-worker-speakers.md`.

## Rulings

- Worker: `DiarizeJobs` (one at a time, a thread per job, temporary `system.wav`, cancel stops the diarizer) and `EmbedService` (kept, locked); routes `POST /diarize?min_speakers&max_speakers` (WAV body) → 202 `{job_id}`, `GET /diarize/{id}` → `{state, turns, message}`, `DELETE /diarize/{id}`, `POST /embed` (float32) → `{vector}`; only with `HF_TOKEN` on the worker (else 503 `worker_speakers_unavailable`); capabilities add `speakers`.
- Engine: `WorkerClient.diarize_start/status/cancel`, `embed`; `WorkerDiarizer` (`Cancellable`: DELETE the job; poll 1 s; unreachable → local pyannote once with the notice) and `WorkerEmbedder` (same switch); `DIARIZERS` / `EMBEDDERS["vozata_worker"]`; `build_transcriber`'s probe / relocation / fallback shared as `_reach_worker`; notices passed to the session's and the queue's diarizer and embedder factories.
- Gate: `GpuUsage.speakers_fallback`; with the worker, `speakers` / `live_speakers` are false and the queue's diarize step stays gated when the fallback could use this GPU.

## Tasks

- [ ] Task 1: worker services and routes, engine client, providers, wiring, gate, tests; commit `feat: identify speakers on the VozAta worker`.
- [ ] Task 2: docs (worker API, contract, guide), suites, manual check, PR, merge.
