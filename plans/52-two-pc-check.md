# Plan — Phase 52: two-PC end-to-end check

Phase file: `docs/roadmap/phases/52-two-pc-check.md`. Branch `feature/52-two-pc-check`.

## Shape

- `scripts/two_pc_check.py` (developer tool, English output, run with the repo's `.venv` on the
  client PC): pure step functions over `httpx.Client`s, a `StepResult(name, ok, detail)` list and a
  table. `scripts/two_pc_runtime.py`: the thin parts (start / stop the scratch client engine,
  play a WAV on the default output), excluded from the unit tests.
- Tests: `engine/tests/scripts/test_two_pc_check.py` with `httpx.MockTransport` (pass, fail,
  timeout per step), the scratch `.env` text, the synthetic WAV, the table.

## Steps of the script

1. **engine**: a scratch client engine (`python -m vozata serve`, cwd = a new scratch folder
   whose `.env` sets `API_PORT`, `OUTPUT_DIR`, `DATABASE_PATH`, `STT_PROVIDER` /
   `DIARIZATION_PROVIDER` / `TRANSLATION_PROVIDER` = `vozata_worker`, `DIARIZATION_ENABLED=true`,
   `GENERATE_MINUTES=false`, `EXTRACT_ACTION_ITEMS=false`, `WORKER_DISCOVERY_PORT`); never the
   user's `.env`. Or `--engine-url` for one already running.
2. **discover**: `GET /worker/discover` lists the worker (`--worker-name` or the first) with a
   non-loopback URL.
3. **pair**: `POST /worker/pair {url, code}`; `--code`, or `--code auto` reads `/local/status`
   when the worker runs on this PC. The scratch `.env` then holds `WORKER_URL` / `WORKER_TOKEN`.
   `--worker-url` + `--token` skip 2–3.
4. **health**: worker `/health` with the token: speech + translation (+ speakers unless
   `--no-speakers`).
5. **translate**: a known Portuguese sentence → English, non-empty and different.
6. **diarize + cancel**: `POST /diarize` (a synthetic WAV), `DELETE` once running, `cancelled`
   within 5 s.
7. **pre-emption** (`--record`): a client recording (`live_transcription: false`) while a speech
   WAV plays on the default output (`--play`), Stop, wait for the queue's `diarize` step, start a
   second recording; with CUDA on the client the step must go `paused` (the gate of phase 40),
   without CUDA it must keep running (worker speakers do not use this PC's GPU). Stop and delete
   the second recording, wait for the first to be `done`, report its speaker count.

Exit code 0 when every step that ran passed.

## Docs

`docs/two-pc-check.md`: prerequisites, how to run the script on the client PC, the manual UI
steps (Find workers + pairing in the app, the three switches, the sidebar line, the fallback
notification) with expected results. Link it from `docs/remote-worker.md`.
