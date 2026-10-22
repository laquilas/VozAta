# Phase 45 — Worker on another PC: speaker identification

## Goal

Move speaker identification (pyannote) to the VozAta worker of phase 44: the post-session
diarization of `system.wav` and the live speaker embedder. With `DIARIZATION_PROVIDER=vozata_worker`
the laptop loads no pyannote model; when the worker does not answer, the local pyannote runs and a
`worker_fallback` notification says so.

## Depends on

44

## Read first

- [phase 44](44-worker-speech.md), `docs/roadmap/worker-api.md`
- [phase 14](14-diarization-post.md), [phase 15](15-diarization-live.md)
- `ports.py` (`Diarizer`, `SpeakerEmbedder`, `Cancellable`), `diarization/session_diarization.py`,
  `diarization/subprocess_diarizer.py`, `diarization/subprocess_embedder.py`,
  `diarization/live.py`, `diarization/live_sink.py`, `session_finisher.py` (cancel wiring),
  `processing/gpu_gate.py`, `processing/live_lease.py`

## Scope

**Worker**: `POST /diarize` (upload `system.wav`, `min_speakers`, `max_speakers`) → job id;
`GET /diarize/{id}` → `running` | `done {turns}` | `failed {message}`; `DELETE /diarize/{id}` cancels
(`SubprocessDiarizer.cancel()`); `POST /embed` (float32 samples) → vector; `HF_TOKEN` and the
pyannote models live on the worker; capabilities `["speech", "speakers"]`.

**Engine**: `DIARIZERS["vozata_worker"]` (a `Cancellable` `WorkerDiarizer`: upload, poll, DELETE on
cancel so the queue's `StepCancelled` still works) and `EMBEDDERS["vozata_worker"]` (one request per
clip; the existing latency budget `chunk_seconds` still disables the tagger when too slow);
fallback through the same resolver as phase 44; gate rules `speakers` / `live_speakers` false when
served by the worker; `HF_TOKEN` no longer required on the laptop for the worker provider.

**Tests**: a shared contract suite for `Diarizer` and `SpeakerEmbedder` (new
`tests/diarization/contract.py`) used by the local and the worker providers; job API, cancel,
fallback, gate.

## Design notes

- Only `system.wav` is sent (the mic is never diarized, as today); turns assignment stays local
  (`assign.py`).
- Diarization of a long meeting can take minutes: a job with polling avoids one long HTTP request
  and gives a real cancel.

## Acceptance criteria

- [ ] With the worker, a meeting's speakers are identified after Stop and live, with no pyannote
      on the laptop.
- [ ] Cancelling the diarize step (a live recording takes priority) cancels the worker job.
- [ ] Worker off → local pyannote runs and the notification names the host.

## Tests

Contract suites, worker endpoints with fake providers, client with `httpx.MockTransport`, cancel,
fallback, gate.

## Out of scope

Translation (phase 46); diarizing the microphone channel.

## Kickoff prompt

> Start phase 45 (`docs/roadmap/phases/45-worker-speakers.md`) once phases 44 and 47–50 are merged
> (order chosen by the user): read its
> *Read first* files, write `plans/45-worker-speakers.md`, then implement it task by task.
